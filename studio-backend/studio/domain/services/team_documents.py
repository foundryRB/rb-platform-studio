"""Pure text operations on a team folder's YAML documents.

What remains after onboarding stopped copying a donor app: the helpers the
capability grants use to route their rendered documents into the per-concern
files, the role-to-homepage-group map the skeleton and conformance share, the
isolation check the database grant validates against, and the lifecycle edits
to an app's Application (pause/resume, freeze/resume promotion). Rendering the
skeleton itself now lives in ``team_skeleton``; rendering the grants in
``database_grant`` / ``identity_grant``. Nothing here mirrors one app onto another.
"""

from __future__ import annotations

import re
from collections.abc import Callable

import yaml

from studio.domain.exceptions.pause_conflict_error import PauseConflictError
from studio.domain.exceptions.promotion_conflict_error import PromotionConflictError
from studio.domain.exceptions.promotion_unbound_error import PromotionUnboundError
from studio.domain.services.image_promotion import (
    ANNOTATION_PREFIX,
    FROZEN_TAG_FILTER,
    image_list_aliases,
)

__all__ = [
    "GRANT_FILES",
    "append_document",
    "database_job_is_isolation_clean",
    "find_document",
    "freeze_application_promotion",
    "homepage_group_for_role",
    "pause_application",
    "replace_document",
    "resume_application",
    "resume_application_promotion",
    "split_by_concern",
]

# The homepage tile group each manifest role lands in (ADR-032): the Foundry's
# `parts` under "Foundry", the `output` it runs under "Apps". The platform chart
# ranges over the manifest's two role blocks to build those groups, so the role
# IS the group and a rendered team folder carries no second copy of it; this
# mapping serves conformance, which judges the folders that still do.
_ROLE_HOMEPAGE_GROUP = {"parts": "Foundry", "output": "Apps"}


def homepage_group_for_role(role: str) -> str:
    """The homepage group (gethomepage.dev/group) an app of this manifest role
    belongs to. Unknown roles fall back to Apps (output is the default role)."""
    return _ROLE_HOMEPAGE_GROUP.get(role, "Apps")


_DOC_SEPARATOR = re.compile(r"^---[ \t]*$", flags=re.MULTILINE)

# The per-concern file each of a GRANT's resource kinds lives in. Every file here
# is owned by the grant that wrote it and by nothing else, which is what lets a
# grant survive reconcile: reconcile re-renders the skeleton's files wholesale
# (SKELETON_FILE_ORDER), so a grant document sharing a file with the skeleton is
# deleted the next time the app is reconciled. That is not hypothetical -- the
# grant's Role and RoleBinding used to land in the skeleton's rbac.yaml, and
# reconciling solveos took both out from under a live generator Job, which then
# ran as a ServiceAccount with no permissions and failed out its backoffLimit
# (foundry-platform#100). The grant's RBAC therefore has its own file, and
# INT-SKELETON-001 states the disjointness the two sets must keep.
_GRANT_KIND_TO_FILE = {
    "Role": "grant-rbac.yaml",
    "RoleBinding": "grant-rbac.yaml",
    "ServiceAccount": "serviceaccount.yaml",
    "Job": "jobs.yaml",
    "ConfigMap": "config.yaml",
    "Secret": "secrets.yaml",
}

# Every file a capability grant may write. Public so the disjointness against
# SKELETON_FILE_ORDER is assertable rather than a thing to remember.
GRANT_FILES = frozenset(_GRANT_KIND_TO_FILE.values())

_KIND_LINE = re.compile(r"^kind:\s*(\S+)\s*$", flags=re.MULTILINE)


def split_by_concern(block_text: str) -> tuple[tuple[str, str], ...]:
    """Route a rendered grant's multi-document block into its concern files.

    Splits on document separators and maps each document to its per-concern
    file by kind (ServiceAccount -> serviceaccount.yaml, Role/RoleBinding ->
    grant-rbac.yaml, Job -> jobs.yaml, ConfigMap -> config.yaml). Comments
    travel with the document they precede, so a rendered template's header
    comment lands in the file its first document lands in.

    Only the capability grants route through here; the skeleton renders its own
    files. A kind outside the grant map is a broken template rather than a file
    to invent -- inventing one would land a grant document in a skeleton file
    and put it back in reconcile's path.
    """
    routed: list[tuple[str, str]] = []
    for doc in _DOC_SEPARATOR.split(block_text):
        body = doc.strip("\n")
        if not body.strip():
            continue
        match = _KIND_LINE.search(body)
        if match is None:
            raise ValueError("a rendered document declares no kind; the template is broken")
        kind = match.group(1)
        filename = _GRANT_KIND_TO_FILE.get(kind)
        if filename is None:
            raise ValueError(f"no grant concern file is defined for kind {kind!r}")
        routed.append((filename, body))
    return tuple(routed)


def append_document(existing_text: str | None, doc_text: str) -> str:
    """Append one YAML document to a concern file, creating the file when absent."""
    body = doc_text.strip("\n")
    if existing_text is None or not existing_text.strip():
        return f"{body}\n"
    return f"{existing_text.rstrip()}\n---\n{body}\n"


# The separator kept as its own element, so that joining the split back
# reproduces the file byte-for-byte: even elements are documents, odd ones the
# separators between them.
_DOC_SEPARATOR_KEPT = re.compile(r"(^---[ \t]*$)", flags=re.MULTILINE)


def _identity(chunk: str) -> tuple[str, str] | None:
    """(kind, metadata.name) of one document chunk, or None for anything that is
    not a named Kubernetes document (a blank chunk, a comment-only one, a chunk
    that does not parse)."""
    try:
        doc = yaml.safe_load(chunk)
    except yaml.YAMLError:
        return None
    if not isinstance(doc, dict):
        return None
    metadata = doc.get("metadata")
    name = metadata.get("name") if isinstance(metadata, dict) else None
    return str(doc.get("kind") or ""), str(name or "")


def find_document(text: str, *, kind: str, name: str) -> str | None:
    """The one document in a concern file with this kind and metadata.name, as its
    own text (the comment lines preceding it included, the newlines around it
    stripped), or None when the file carries no such document."""
    chunks = _DOC_SEPARATOR_KEPT.split(text)
    for index, chunk in enumerate(chunks):
        if index % 2 == 0 and _identity(chunk) == (kind, name):
            return chunk.strip("\n")
    return None


def replace_document(text: str, doc_text: str, *, kind: str, name: str) -> str | None:
    """Replace the one document with this kind and metadata.name by ``doc_text``,
    in place, and return the file; None when the file carries no such document.

    Every other byte of the file survives: the other documents, the separators,
    and the newlines around the replaced document, so a concern file that
    carries another grant's documents beside this one changes in exactly the
    one document named. The counterpart of ``append_document`` for a re-render:
    onboarding appends a grant's documents, reconcile replaces them.
    """
    chunks = _DOC_SEPARATOR_KEPT.split(text)
    body = doc_text.strip("\n")
    for index, chunk in enumerate(chunks):
        if index % 2 == 0 and _identity(chunk) == (kind, name):
            lead = chunk[: len(chunk) - len(chunk.lstrip("\n"))]
            trail = chunk[len(chunk.rstrip("\n")) :]
            chunks[index] = f"{lead}{body}{trail}"
            return "".join(chunks)
    return None


def database_job_is_isolation_clean(*, job_text: str, app: str) -> bool:
    """Whether a database provisioning Job carries both per-app isolation fixes.

    A Job is isolation-clean when it mounts a PER-APP credential name
    (``pg-app-<app>``, never the shared ``pg-app`` the first onboarded app owns) AND
    self-grants SET ROLE on the owner before creating the database
    (``GRANT <app> TO CURRENT_USER WITH SET TRUE``). A Job missing either would
    reintroduce the shared-name collision or the PG16 "must be able to SET ROLE"
    failure (sabbito-bazarrito#7). Used to validate the rendered grant fails closed
    on a template regression, and mirrors the platform's INT-FOUNDRY-040/041 gate.
    """
    per_app_credential = f"secretName: pg-app-{app}" in job_text
    set_role_grant = re.search(
        rf'GRANT\s+"?{re.escape(app)}"?\s+TO\s+CURRENT_USER\s+WITH\s+SET',
        job_text,
        flags=re.IGNORECASE,
    )
    return per_app_credential and set_role_grant is not None


def pause_application(manifest_text: str, *, app: str) -> str:
    """Add the scale-to-zero override to the app's Application source.

    Inserts spec.source.helm.valuesObject.<app>.paused: true as the first child
    of the Application document's source mapping (teams/<app>/application.yaml),
    leaving every other byte untouched. Idempotent: an already-paused file is
    returned unchanged.
    """
    return _map_application_doc(manifest_text, lambda doc: _add_pause_override(doc, app=app))


def resume_application(manifest_text: str, *, app: str) -> str:
    """Remove the scale-to-zero override from the app's Application source.

    Deletes the helm: block under the Application document's source mapping,
    restoring the file byte-for-byte to its running form. Idempotent: a
    running file (no override) is returned unchanged.
    """
    return _map_application_doc(manifest_text, _remove_pause_override)


def freeze_application_promotion(manifest_text: str, *, app: str) -> str:
    """Freeze image promotion: give every declared alias the freeze tag filter.

    Inserts ``<prefix><alias>.ignore-tags: "*"`` after each alias's own
    annotations in the Application document (teams/<app>/application.yaml),
    leaving every other byte untouched. The binding itself survives - the
    image-list, the helm paths, the released set - so every promotion
    conformance row keeps running and the status read keeps reporting the
    pinned tag; only the candidate tags go away.

    Idempotent: an alias already carrying the sentinel is skipped, so a fully
    frozen file is returned unchanged (and a partially frozen one, only
    reachable by a hand edit, is completed). Raises PromotionUnboundError when
    the Application declares no image-list, and PromotionConflictError when an
    alias already carries an ignore-tags the freeze would have to overwrite.
    """
    return _map_application_doc(manifest_text, lambda doc: _add_freeze_filters(doc, app=app))


def resume_application_promotion(manifest_text: str, *, app: str) -> str:
    """Resume image promotion: drop the freeze tag filter from every alias.

    Removes only the lines this module wrote (a declared alias's ignore-tags
    whose value is exactly the sentinel), restoring the file byte-for-byte to
    its promoting form and leaving an operator's own ignore-tags alone.
    Idempotent: an unfrozen file is returned unchanged.
    """
    return _map_application_doc(manifest_text, _remove_freeze_filters)


# One Image Updater annotation line: its indentation, the key after the
# prefix (image-list, or an alias-scoped <alias>.<something>), and its value.
_IMAGE_UPDATER_LINE = re.compile(
    rf"^(?P<indent>[ \t]*){re.escape(ANNOTATION_PREFIX)}"
    r"(?P<key>[^:\s]+):[ \t]*(?P<value>.*?)[ \t]*$"
)
_IGNORE_TAGS = ".ignore-tags"


def _scalar(value: str) -> str:
    """A YAML annotation value with its surrounding quotes stripped."""
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    return text


def _declared_aliases(lines: list[str]) -> tuple[tuple[str, ...], int, str]:
    """(aliases, the image-list line's index, its indentation) for a document."""
    for index, line in enumerate(lines):
        match = _IMAGE_UPDATER_LINE.match(line)
        if match is not None and match.group("key") == "image-list":
            return (
                image_list_aliases(_scalar(match.group("value"))),
                index,
                match.group("indent"),
            )
    return (), -1, ""


def _add_freeze_filters(doc: str, *, app: str) -> str:
    lines = doc.split("\n")
    aliases, list_index, indent = _declared_aliases(lines)
    if not aliases:
        raise PromotionUnboundError(app)
    insertions: list[tuple[int, str]] = []
    for alias in aliases:
        # Land the filter with the alias's own annotations (the canonical
        # render groups them), falling back to the image-list line for an
        # alias that carries none.
        anchor = list_index
        existing: str | None = None
        for index, line in enumerate(lines):
            match = _IMAGE_UPDATER_LINE.match(line)
            if match is None or not match.group("key").startswith(f"{alias}."):
                continue
            anchor = index
            if match.group("key") == f"{alias}{_IGNORE_TAGS}":
                existing = match.group("value")
        if existing is not None:
            if _scalar(existing) == FROZEN_TAG_FILTER:
                continue  # already frozen
            raise PromotionConflictError(app, alias, existing.strip())
        insertions.append(
            (
                anchor,
                f'{indent}{ANNOTATION_PREFIX}{alias}{_IGNORE_TAGS}: "{FROZEN_TAG_FILTER}"',
            )
        )
    for index, line in sorted(insertions, reverse=True):
        lines.insert(index + 1, line)
    return "\n".join(lines)


def _remove_freeze_filters(doc: str) -> str:
    lines = doc.split("\n")
    aliases, _, _ = _declared_aliases(lines)
    kept: list[str] = []
    for line in lines:
        match = _IMAGE_UPDATER_LINE.match(line)
        if (
            match is not None
            and match.group("key").endswith(_IGNORE_TAGS)
            and match.group("key").removesuffix(_IGNORE_TAGS) in aliases
            and _scalar(match.group("value")) == FROZEN_TAG_FILTER
        ):
            continue
        kept.append(line)
    return "\n".join(kept)


def _map_application_doc(text: str, transform: Callable[[str], str]) -> str:
    docs = _DOC_SEPARATOR.split(text)
    changed = [transform(doc) if "kind: Application" in doc else doc for doc in docs]
    return "---".join(changed) if changed != docs else text


def _add_pause_override(doc: str, *, app: str) -> str:
    if _PAUSED_OVERRIDE.search(doc):
        return doc
    match = _SOURCE_LINE.search(doc)
    if match is None:
        return doc
    if _source_has_helm_child(doc, match):
        raise PauseConflictError(app)
    child = match.group("indent") + "  "
    block = (
        f"{child}helm:\n"
        f"{child}  valuesObject:\n"
        f"{child}    {app}:\n"
        f"{child}      paused: true\n"
    )
    cut = match.end() + 1  # just past the newline ending the `source:` line
    return doc[:cut] + block + doc[cut:]


def _source_has_helm_child(doc: str, match: re.Match[str]) -> bool:
    """Whether the matched source: mapping already declares a helm: child.

    Pause reserves spec.source.helm for the scale-to-zero override alone
    (ADR-030), so it is always the block this module inserts. A foreign helm
    block means that invariant is broken; pause refuses rather than emit a
    duplicate mapping key that YAML last-key-wins would silently drop.
    """
    indent = len(match.group("indent"))
    child = indent + 2
    for line in doc[match.end() + 1 :].splitlines():
        if not line.strip():
            continue
        depth = len(line) - len(line.lstrip(" "))
        if depth <= indent:
            return False  # dedent to source's level or shallower ends the block
        if depth == child and line.lstrip(" ").startswith("helm:"):
            return True
    return False


def _remove_pause_override(doc: str) -> str:
    return _HELM_BLOCK.sub("", doc, count=1)


_SOURCE_LINE = re.compile(r"^(?P<indent>[ \t]*)source:[ \t]*$", flags=re.MULTILINE)
_HELM_BLOCK = re.compile(
    r"^(?P<indent>[ \t]*)helm:[ \t]*\n(?:(?P=indent)[ \t]+.*(?:\n|$))*",
    flags=re.MULTILINE,
)
_PAUSED_OVERRIDE = re.compile(r"^\s*paused:\s*true\s*$", flags=re.MULTILINE)
