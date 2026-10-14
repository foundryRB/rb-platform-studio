"""PlatformRepository over a filesystem checkout of the install's deploy branch."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import yaml

from studio.domain.exceptions.sync_failed_error import SyncFailedError
from studio.domain.model.app_entry import AppEntry
from studio.domain.model.default_broker import DefaultBroker
from studio.domain.model.install_organisation import InstallOrganisation
from studio.domain.model.install_registry import InstallRegistry
from studio.domain.model.intent_claim import IntentClaim
from studio.domain.model.team_manifest import TeamManifest
from studio.domain.services.environments import declared_environments
from studio.domain.services.image_promotion import PROMOTION_UNBOUND, promotion_mode
from studio.domain.services.yaml_scalar import yaml_quoted, yaml_scalar
from studio.logging import get_logger

__all__ = ["FsPlatformRepository"]

logger = get_logger(__name__)

_MANIFEST_FILE = "foundry.yaml"
_VALUES_FILE = "values.yaml"
_INTENT_FILE = "intent.yaml"
_ROLES = ("parts", "output")
# A role block header. The empty flow sequence (`output: []`) is how a manifest
# carries a role it has no entries of yet, so it heads the block exactly as a bare
# `output:` does; matching only the bare form is what once appended a SECOND
# top-level `output:` key on an install's first output onboarding, leaving the
# manifest with a duplicate key that only last-key-wins parsing rescued.
_ROLE_HEAD = {
    role: re.compile(rf"^(?P<key>{role}\s*:)\s*(?P<empty>\[\s*\])?(?P<trail>\s*(?:#.*)?)$")
    for role in _ROLES
}
_ENTRY_HEAD = re.compile(r"^(?P<indent>\s*)-\s+name:\s*(?P<name>\S+)\s*$")


def _listener_hostname(doc: dict) -> str:
    """The hostname a Gateway document's first listener declares, "" when absent."""
    listeners = (doc.get("spec") or {}).get("listeners") or []
    return str(listeners[0].get("hostname") or "") if listeners else ""


class FsPlatformRepository:
    """Reads and writes the deploy-branch checkout, preserving file text outside
    the exact regions a mutation touches (comments and layout survive)."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def manifest_entries(self) -> tuple[AppEntry, ...]:
        raw = yaml.safe_load(self._read_required(_MANIFEST_FILE)) or {}
        zone = self.zone()
        entries: list[AppEntry] = []
        for role in _ROLES:
            for item in raw.get(role) or []:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "")
                # The endpoint follows the Gateway listener: external-dns publishes
                # the record from it, so an app on a short host serves its MCP there
                # and the derived <name>.<zone> would advertise a dead route. Read
                # only for a flagged entry - the folder scan is not free, and an app
                # not exposing MCP has no endpoint to report.
                mcp_url = None
                if item.get("mcp") is True:
                    host = self._gateway_hostname(name) or f"{name}.{zone}"
                    mcp_url = f"https://{host}/mcp"
                entries.append(
                    AppEntry(
                        name=name,
                        mcp_url=mcp_url,
                        role=role,
                        display=str(item.get("display") or ""),
                        description=str(item.get("description") or ""),
                        icon=str(item.get("icon") or ""),
                        # Absent on every entry that ships from a repository of
                        # its own name, which is most of them; AppEntry.repo_name
                        # carries the default so no reader here or downstream
                        # re-derives it.
                        repo=str(item.get("repo") or ""),
                    )
                )
        return tuple(entries)

    def add_manifest_entry(
        self, *, name: str, display: str, icon: str, mcp: bool, role: str,
        description: str = "", repo: str = "",
    ) -> None:
        text = self._read_required(_MANIFEST_FILE)
        newline = "\r\n" if "\r\n" in text else "\n"
        lines = text.split(newline)
        lines = _insert_manifest_entry(
            lines, role=role, name=name, display=display, icon=icon, mcp=mcp,
            description=description, repo=repo,
        )
        self.raw_write(_MANIFEST_FILE, newline.join(lines))
        logger.info(
            "Added %s to %s under %s (mcp=%s, repo=%s)",
            name, _MANIFEST_FILE, role, mcp, repo or name,
        )

    def remove_manifest_entry(self, name: str) -> None:
        """Remove the app's entry from whichever role block carries it,
        touching nothing else (the inverse of add_manifest_entry's surgery)."""
        text = self._read_required(_MANIFEST_FILE)
        newline = "\r\n" if "\r\n" in text else "\n"
        lines = text.split(newline)
        lines = _remove_manifest_entry(lines, name=name)
        self.raw_write(_MANIFEST_FILE, newline.join(lines))
        logger.info("Removed %s from %s", name, _MANIFEST_FILE)

    def zone(self) -> str:
        raw = yaml.safe_load(self._read_required(_VALUES_FILE)) or {}
        return str(raw.get("zone") or "")

    def install(self) -> str:
        raw = yaml.safe_load(self._read_required(_MANIFEST_FILE)) or {}
        return str(raw.get("install") or "")

    def environments(self) -> tuple[str, ...]:
        raw = yaml.safe_load(self._read_required(_MANIFEST_FILE)) or {}
        return declared_environments(raw)

    def tunnel_id(self) -> str:
        raw = yaml.safe_load(self._read_required(_VALUES_FILE)) or {}
        return str(raw.get("tunnelId") or "")

    def operators(self) -> tuple[str, ...]:
        raw = yaml.safe_load(self._read_required(_VALUES_FILE)) or {}
        return tuple(str(op) for op in (raw.get("operators") or []))

    def default_brokers(self) -> tuple[DefaultBroker, ...]:
        raw = yaml.safe_load(self._read_required(_VALUES_FILE)) or {}
        brokers = []
        for item in raw.get("defaultBrokers") or []:
            if not isinstance(item, dict):
                continue
            config = item.get("config") or {}
            brokers.append(
                DefaultBroker(
                    alias=str(item.get("alias") or ""),
                    provider_id=str(item.get("providerId") or ""),
                    secret_ref=str(item.get("secretRef") or ""),
                    display_name=str(item.get("displayName") or ""),
                    config=dict(config) if isinstance(config, dict) else {},
                )
            )
        return tuple(brokers)

    def login_theme(self) -> str:
        raw = yaml.safe_load(self._read_required(_VALUES_FILE)) or {}
        identity = raw.get("identity")
        theme = identity.get("loginTheme") if isinstance(identity, dict) else None
        name = theme.get("name") if isinstance(theme, dict) else None
        return str(name or "").strip()

    def registry(self) -> InstallRegistry:
        raw = yaml.safe_load(self._read_required(_VALUES_FILE)) or {}
        block = raw.get("registry")
        if not isinstance(block, dict):
            return InstallRegistry()
        return InstallRegistry(
            host=str(block.get("host") or ""),
            owner=str(block.get("owner") or ""),
            pull_secret=str(block.get("pullSecret") or ""),
        )

    def organisation(self) -> InstallOrganisation:
        raw = yaml.safe_load(self._read_required(_VALUES_FILE)) or {}
        return InstallOrganisation.from_values(raw if isinstance(raw, dict) else {})

    def team_files(self, name: str) -> tuple[str, ...]:
        folder = self._root / "teams" / name
        if not folder.is_dir():
            return ()
        return tuple(
            sorted(p.name for p in folder.iterdir() if p.is_file() and p.suffix == ".yaml")
        )

    def _gateway_hostname(self, name: str) -> str:
        """The hostname the app's Gateway listener declares, "" when unreadable.

        Empty for an app whose team folder is absent or carries no Gateway; the
        caller falls back to the install's naming convention there.
        """
        for doc in self.team_documents(name):
            if doc.get("kind") == "Gateway":
                return _listener_hostname(doc)
        return ""

    def team_file_text(self, name: str, filename: str) -> str | None:
        return self.raw_read(f"teams/{name}/{filename}")

    def write_team_file(self, name: str, filename: str, text: str) -> None:
        self.raw_write(f"teams/{name}/{filename}", text)

    def team_documents(self, name: str) -> tuple[dict, ...]:
        docs: list[dict] = []
        for filename in self.team_files(name):
            text = self.team_file_text(name, filename)
            if text is None:
                continue
            docs.extend(doc for doc in yaml.safe_load_all(text) if isinstance(doc, dict))
        return tuple(docs)

    def team_manifest(self, name: str) -> TeamManifest | None:
        if not self.team_files(name):
            return None
        hostname = repo_url = target_revision = ""
        display_name = description = icon = ""
        has_database = False
        has_identity = False
        has_events = False
        paused = False
        promotion = PROMOTION_UNBOUND
        for doc in self.team_documents(name):
            kind = doc.get("kind")
            metadata = doc.get("metadata") or {}
            spec = doc.get("spec") or {}
            if kind == "Gateway":
                hostname = _listener_hostname(doc) or hostname
            elif kind == "Application":
                source = spec.get("source") or {}
                repo_url = str(source.get("repoURL") or "")
                target_revision = str(source.get("targetRevision") or "")
                values_object = (source.get("helm") or {}).get("valuesObject") or {}
                paused = (values_object.get(name) or {}).get("paused") is True
                annotations = metadata.get("annotations") or {}
                promotion = promotion_mode(
                    {str(key): str(value) for key, value in annotations.items()}
                )
            elif kind == "HTTPRoute":
                annotations = metadata.get("annotations") or {}
                if "gethomepage.dev/name" in annotations:
                    display_name = str(annotations.get("gethomepage.dev/name") or "")
                    description = str(annotations.get("gethomepage.dev/description") or "")
                    icon = str(annotations.get("gethomepage.dev/icon") or "")
            elif kind == "Job" and str(metadata.get("name") or "") == f"pg-{name}-provision":
                has_database = True
            elif (
                kind == "ConfigMap"
                and str(metadata.get("name") or "") == f"keycloak-realm-{name}"
            ):
                has_identity = True
            elif kind == "Job" and str(metadata.get("name") or "") == f"nats-sign-{name}":
                # The signing Job is the marker, not the generator: a key minted
                # with nothing to sign it is not yet a grant.
                has_events = True
        return TeamManifest(
            app=name,
            hostname=hostname,
            repo_url=repo_url,
            target_revision=target_revision,
            display_name=display_name,
            description=description,
            icon=icon,
            has_database=has_database,
            has_identity=has_identity,
            has_events=has_events,
            paused=paused,
            promotion=promotion,
        )

    def claims(self) -> tuple[IntentClaim, ...]:
        raw = yaml.safe_load(self._intent_text()) or {}
        claims: list[IntentClaim] = []
        for claim_id, body in raw.items():
            if not isinstance(body, dict):
                continue
            test = body.get("test") or {}
            claims.append(
                IntentClaim(
                    claim_id=str(claim_id),
                    summary=str(body.get("statement") or ""),
                    status=str(body.get("status") or ""),
                    scope=str(test.get("scope") or ""),
                    criticality=str(body.get("criticality") or ""),
                )
            )
        return tuple(claims)

    def raw_read(self, rel_path: str) -> str | None:
        path = self._root / rel_path
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8")

    def raw_write(self, rel_path: str, text: str) -> None:
        path = self._root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="")

    def raw_delete(self, rel_path: str) -> None:
        path = self._root / rel_path
        if path.is_file():
            path.unlink()
        # Prune directories the delete emptied (a rolled-back onboarding must
        # not leave a stray teams/<app>/ shell behind), stopping at the root.
        parent = path.parent
        while parent != self._root and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent

    def _intent_text(self) -> str:
        """The platform's intent.yaml: the working tree when it carries one,
        else the canonical source branch of the same clone.

        The deploy branch holds only the installed state (ADR-032); the
        conformance claims live on the platform repo's main, which the studio's
        clone carries as a ref. Reading the blob straight from git keeps the
        claims surface serving without a second checkout.
        """
        text = self.raw_read(_INTENT_FILE)
        if text is not None:
            return text
        for ref in ("origin/main", "main"):
            proc = subprocess.run(
                ["git", "-C", str(self._root), "show", f"{ref}:{_INTENT_FILE}"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if proc.returncode == 0:
                return proc.stdout
        raise SyncFailedError(
            f"no {_INTENT_FILE} in the working tree at {self._root} and no "
            "main ref to read it from"
        )

    def _read_required(self, rel_path: str) -> str:
        text = self.raw_read(rel_path)
        if text is None:
            raise SyncFailedError(f"install checkout is missing {rel_path} at {self._root}")
        return text


def _render_entry(
    *, indent: str, name: str, display: str, icon: str, mcp: bool, description: str = "",
    repo: str = "",
) -> list[str]:
    lines = [f"{indent}- name: {name}"]
    # Rendered only when it actually differs from the name. An app shipping from
    # a repository of its own name declares nothing, so existing manifests take
    # no churn and a `repo:` line in the file always means exactly one thing:
    # these two identities are not the same string here.
    if repo and repo != name:
        lines.append(f"{indent}  repo: {repo}")
    lines.append(f"{indent}  display: {yaml_scalar(display)}")
    if description:
        # Always double-quoted: a description is free text (commas, colons)
        # and a raw scalar would corrupt the manifest.
        lines.append(f"{indent}  description: {yaml_quoted(description)}")
    lines.append(f"{indent}  icon: {yaml_scalar(icon)}")
    if mcp:
        lines.append(f"{indent}  mcp: true")
    return lines


def _insert_manifest_entry(
    lines: list[str], *, role: str, name: str, display: str, icon: str, mcp: bool,
    description: str = "", repo: str = "",
) -> list[str]:
    """Insert one app entry into the role's sorted block, touching nothing else.

    Manifest entries are multi-line list items (`- name:` plus indented
    attribute lines); the block ends at the next top-level key. The entry lands
    after the last existing item whose name sorts before it, with the block's
    own item indentation. An install onboarding its first entry of a role (the
    block header itself absent, e.g. an install that has so far only carried
    `parts` onboarding its first `output` app) gets a fresh block appended at
    the end of the file, rather than failing an otherwise-valid onboarding.

    A role the manifest carries as an empty flow sequence (`output: []`, the
    shape a bare install's manifest starts in) heads its block like any other:
    the sequence is dropped and the entry lands under the key already there.
    Reading that header as absent is what once appended a duplicate top-level
    key on an install's first onboarding of a role.
    """
    head = _ROLE_HEAD[role]
    matched = next(
        ((i, m) for i, line in enumerate(lines) if (m := head.match(line))), None
    )
    if matched is None:
        return _append_new_role_block(
            lines, role=role, name=name, display=display, icon=icon, mcp=mcp,
            description=description, repo=repo,
        )
    head_index, head_match = matched
    if head_match.group("empty"):
        # `output: []` cannot carry list items on the lines below it: open the
        # block by dropping the empty sequence, keeping the key and any comment.
        lines = (
            lines[:head_index]
            + [head_match.group("key") + head_match.group("trail")]
            + lines[head_index + 1 :]
        )
    indent = ""
    insert_at = head_index + 1
    index = head_index + 1
    while index < len(lines):
        line = lines[index]
        match = _ENTRY_HEAD.match(line)
        if match:
            indent = match.group("indent")
            if match.group("name") < name:
                insert_at = _end_of_item(lines, index, indent)
                index = insert_at
                continue
            index = _end_of_item(lines, index, indent)
            continue
        if line.strip() == "" or line.lstrip().startswith("#"):
            index += 1
            continue
        break  # a new top-level key ends the block
    rendered = _render_entry(
        indent=indent, name=name, display=display, icon=icon, mcp=mcp,
        description=description, repo=repo,
    )
    return lines[:insert_at] + rendered + lines[insert_at:]


def _append_new_role_block(
    lines: list[str], *, role: str, name: str, display: str, icon: str, mcp: bool,
    description: str = "", repo: str = "",
) -> list[str]:
    """The manifest carries no entries of this role yet: append a fresh
    top-level block at the end, in the fleet's un-indented list style (the
    same shape an existing sibling-role block already uses)."""
    block = [f"{role}:"] + _render_entry(
        indent="", name=name, display=display, icon=icon, mcp=mcp,
        description=description, repo=repo,
    )
    if lines and lines[-1].strip() != "":
        return lines + [""] + block
    return lines + block


def _remove_manifest_entry(lines: list[str], *, name: str) -> list[str]:
    """Remove one app's multi-line entry (`- name:` plus its attribute lines)
    from whichever role block carries it, leaving every other line untouched.
    A name the manifest does not carry removes nothing (the caller validates
    existence; this stays a pure line operation)."""
    for index, line in enumerate(lines):
        match = _ENTRY_HEAD.match(line)
        if match and match.group("name") == name:
            end = _end_of_item(lines, index, match.group("indent"))
            return lines[:index] + lines[end:]
    return lines


def _end_of_item(lines: list[str], start: int, indent: str) -> int:
    """The index just past a list item's attribute lines (deeper-indented rows)."""
    index = start + 1
    attr_depth = len(indent) + 2
    while index < len(lines):
        line = lines[index]
        if line.strip() == "":
            break
        depth = len(line) - len(line.lstrip(" "))
        if depth < attr_depth and not line.lstrip().startswith("#"):
            break
        index += 1
    return index
