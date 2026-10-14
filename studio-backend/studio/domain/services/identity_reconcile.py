"""Re-render an app's identity grant in place: the template's half replaced, the team's kept.

A realm carries what it was rendered with until it is reconciled (ADR-045): an
install that declares a default broker after granting realms, or names a login
theme, has realms on its branch that no longer say what the canonical template
would say today, and ``grant_drift`` reports exactly that. This module is the
other half, the repair: it takes the grant's fresh render and the team folder as
it stands, and produces the folder with the grant's two documents (the realm
ConfigMap and its provisioning Job) replaced by the render, each in the file
that carries it, with every other byte of every file untouched.

Two rules make that safe to do to a live realm, and both come from defects.

**Only the grant's own documents are replaced, never a file.** Reconcile once
rewrote a skeleton file wholesale and took a live generator's Role and
RoleBinding out from under it (foundry-platform#100). The identity grant's
documents share their concern files with the database grant's Jobs and with
the ``gen-keycloak-<app>`` generator that mints the app's own credential, so a
re-render addresses each document by kind and name (``replace_document``) and
the file around it survives byte-for-byte. The generator, its ServiceAccount
and RBAC, the client, the host: none of them is this module's to touch, and
none of them is.

**The realm's users are the team's and are carried across.** The users list IS
the access allowlist (ADR-031): people are admitted by hand, by design, and a
render keyed on the app name cannot know them. Normalising the fleet against the
template once proposed deleting an admitted operator from two live realms
(INT-GRANT-007). So the re-rendered ConfigMap carries the template's own users
(the realm admin, platform-owned, re-rendered like the rest) followed by every
entry the branch admitted, verbatim, comments and all. Everything else in the
realm is the template's: a provider a team wants for itself lives in the app's
own chart, applied as its realm-scoped admin (ADR-045 section 2), and a provider
someone hand-applied to the platform's copy is what a re-render supersedes.
"""

from __future__ import annotations

import re
import textwrap
from collections.abc import Mapping
from dataclasses import dataclass

import yaml

from studio.domain.services.team_documents import (
    append_document,
    find_document,
    replace_document,
    split_by_concern,
)

__all__ = [
    "IdentityReconciliation",
    "carry_admitted_users",
    "realm_facts",
    "reconcile_identity_documents",
]

# The realm body is a block scalar under data.realm.yaml, so its top-level keys
# sit at exactly four spaces and its user entries at six.
_REALM_INDENT = 4
_ENTRY_INDENT = 6
_USERS_LINE = re.compile(r"^ {4}users:[ \t]*$")
_REALM_FILE = "realm.yaml"


@dataclass(frozen=True)
class IdentityReconciliation:
    """One app's team folder after its identity grant is re-rendered.

    ``files`` is every concern file whose text changes, with its new text; empty
    means the branch already carries exactly what the template renders today,
    which is the idempotent case and opens nothing. ``previous_aliases`` and
    ``previous_login_theme`` are what the realm carried before, read off the
    branch so the change can be explained. ``carried_users`` names the admitted
    users carried across beside the realm admin.
    """

    app: str
    files: tuple[tuple[str, str], ...]
    previous_aliases: tuple[str, ...]
    previous_login_theme: str
    carried_users: tuple[str, ...]

    @property
    def current(self) -> bool:
        return not self.files


def realm_facts(config_doc: str) -> tuple[tuple[str, ...], str]:
    """(identity provider aliases, login theme) the realm ConfigMap declares.

    Read off the branch before the re-render, so the pull request can say which
    brokers are new to the realm, which it already carried, and whether the theme
    moved. An unreadable realm reads as declaring nothing.
    """
    try:
        document = yaml.safe_load(config_doc)
        data = (document or {}).get("data") if isinstance(document, dict) else None
        realm = yaml.safe_load((data or {}).get(_REALM_FILE) or "") or {}
    except yaml.YAMLError:
        return (), ""
    if not isinstance(realm, dict):
        return (), ""
    aliases = tuple(
        str(provider["alias"])
        for provider in realm.get("identityProviders") or []
        if isinstance(provider, dict) and provider.get("alias")
    )
    return aliases, str(realm.get("loginTheme") or "")


def _users_block(lines: list[str]) -> tuple[int, int] | None:
    """(start, end) line indices of the realm's ``users`` block within a ConfigMap
    document: from the ``users:`` line to the next top-level realm key or the end
    of the block scalar, exclusive. Comment and blank lines immediately before the
    next key introduce that key and are left to it."""
    start = next((i for i, line in enumerate(lines) if _USERS_LINE.match(line)), None)
    if start is None:
        return None
    end = len(lines)
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        is_comment = line.lstrip().startswith("#")
        if indent < _REALM_INDENT or (indent == _REALM_INDENT and not is_comment):
            end = index
            break
    if end < len(lines):
        while end - 1 > start and (
            not lines[end - 1].strip() or lines[end - 1].lstrip().startswith("#")
        ):
            end -= 1
    return start, end


def _user_entries(lines: list[str]) -> list[str]:
    """The block's list entries as their own texts, each carrying the comment lines
    that introduce it (a comment precedes what it describes, which is how the
    template's own admin comment travels with the admin)."""
    entries: list[list[str]] = []
    pending: list[str] = []
    for line in lines:
        stripped = line.strip()
        indent = len(line) - len(line.lstrip(" "))
        if indent == _ENTRY_INDENT and stripped.startswith("-"):
            entries.append([*pending, line])
            pending = []
        elif not stripped or (stripped.startswith("#") and indent <= _ENTRY_INDENT):
            pending.append(line)
        elif entries:
            entries[-1].append(line)
        else:
            pending.append(line)
    if entries and pending:
        entries[-1].extend(pending)
    return ["".join(entry).rstrip("\n") + "\n" for entry in entries]


def _username(entry: str) -> str | None:
    try:
        parsed = yaml.safe_load(textwrap.dedent(entry))
    except yaml.YAMLError:
        return None
    if isinstance(parsed, list) and len(parsed) == 1 and isinstance(parsed[0], dict):
        value = parsed[0].get("username")
        return str(value) if value is not None else None
    return None


def carry_admitted_users(
    rendered_doc: str, existing_doc: str, app: str
) -> tuple[str, tuple[str, ...]]:
    """The rendered realm ConfigMap with every user the branch admitted carried in.

    The template's own users block is kept as rendered (the realm admin is
    platform-owned: its fields, its comments, its credential substitution), and
    every entry of the existing realm's users list whose username is not the
    admin's is appended after it verbatim, so an admitted person survives the
    re-render with the exact text someone wrote for them. Returns the merged
    document and the usernames carried. A render with no admitted users comes
    back byte-identical to ``rendered_doc``, which is what makes a reconciled
    realm indistinguishable from a freshly onboarded one. An entry that cannot be
    read is carried rather than dropped: the failure this guards against is
    deleting a person, never keeping one.
    """
    existing_lines = existing_doc.splitlines(keepends=True)
    existing_block = _users_block(existing_lines)
    if existing_block is None:
        return rendered_doc, ()
    start, end = existing_block
    admin = f"{app}-admin"
    kept = [
        (entry, _username(entry))
        for entry in _user_entries(existing_lines[start + 1 : end])
        if _username(entry) != admin
    ]
    if not kept:
        return rendered_doc, ()
    rendered_lines = rendered_doc.splitlines(keepends=True)
    rendered_block = _users_block(rendered_lines)
    if rendered_block is None:
        raise ValueError(
            f"the canonical realm template renders no users block for {app!r}; "
            "the template is broken"
        )
    _r_start, r_end = rendered_block
    head = "".join(rendered_lines[:r_end])
    if not head.endswith("\n"):
        head += "\n"
    tail = "".join(rendered_lines[r_end:])
    merged = head + "".join(entry for entry, _name in kept) + tail
    return merged.rstrip("\n"), tuple(name or "<unnamed>" for _entry, name in kept)


def _rendered_identity(doc: str) -> tuple[str, str]:
    document = yaml.safe_load(doc)
    if not isinstance(document, dict):
        raise ValueError("a rendered identity document is not a mapping; the template is broken")
    return str(document.get("kind") or ""), str((document.get("metadata") or {}).get("name") or "")


def reconcile_identity_documents(
    *, app: str, rendered_blocks: str, team_files: Mapping[str, str]
) -> IdentityReconciliation:
    """The team folder with the identity grant's documents replaced by their render.

    ``rendered_blocks`` is the grant's canonical render for this app, host and
    declaration (``render_identity_blocks``); ``team_files`` maps each filename in
    ``teams/<app>/`` to its text. Each rendered document is routed to its concern
    file (``split_by_concern``) and replaces the document of the same kind and name
    wherever the folder carries it, the concern file first; a document the folder
    carries nowhere is appended to its concern file, the way onboarding wrote it.
    The realm ConfigMap is merged with the branch's admitted users before it is
    written (``carry_admitted_users``). Every file not named in the result is
    byte-identical to what came in.
    """
    files = dict(team_files)
    previous_aliases: tuple[str, ...] = ()
    previous_theme = ""
    carried: tuple[str, ...] = ()
    for concern, rendered_doc in split_by_concern(rendered_blocks):
        kind, name = _rendered_identity(rendered_doc)
        candidates = [concern, *sorted(f for f in files if f != concern)]
        home = next(
            (
                filename
                for filename in candidates
                if filename in files
                and find_document(files[filename], kind=kind, name=name) is not None
            ),
            None,
        )
        if home is None:
            files[concern] = append_document(files.get(concern), rendered_doc)
            continue
        existing = find_document(files[home], kind=kind, name=name) or ""
        body = rendered_doc
        if kind == "ConfigMap":
            previous_aliases, previous_theme = realm_facts(existing)
            body, carried = carry_admitted_users(rendered_doc, existing, app)
        replaced = replace_document(files[home], body, kind=kind, name=name)
        if replaced is not None:
            files[home] = replaced
    changed = tuple(
        (filename, text)
        for filename, text in sorted(files.items())
        if text != team_files.get(filename)
    )
    return IdentityReconciliation(
        app=app,
        files=changed,
        previous_aliases=previous_aliases,
        previous_login_theme=previous_theme,
        carried_users=carried,
    )
