"""Outbound port: read and write the install's checkout of the platform repo."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from studio.domain.model.app_entry import AppEntry
from studio.domain.model.default_broker import DefaultBroker
from studio.domain.model.install_organisation import InstallOrganisation
from studio.domain.model.install_registry import InstallRegistry
from studio.domain.model.intent_claim import IntentClaim
from studio.domain.model.team_manifest import TeamManifest

__all__ = ["PlatformRepository"]


@runtime_checkable
class PlatformRepository(Protocol):
    """File access to the install's deploy-branch checkout: the manifest
    (foundry.yaml), the install values (values.yaml), the teams/<app>/ folders,
    and the platform's conformance claims.

    Writes preserve the surrounding text byte-for-byte outside the touched
    region, so a rolled-back onboarding leaves the checkout byte-identical.
    """

    def manifest_entries(self) -> tuple[AppEntry, ...]:
        """The foundry.yaml app entries (parts + output), with derived MCP endpoints."""
        ...

    def add_manifest_entry(
        self, *, name: str, display: str, icon: str, mcp: bool, role: str,
        description: str = "", repo: str = "",
    ) -> None:
        """Insert the app into the manifest's role list (sorted by name).

        ``description`` rides into the entry (double-quoted free text) so the
        manifest is the single source of every tile fact; empty writes no
        description line (entries authored before the field moved here).

        ``repo`` is the repository the app ships from, written only when it
        differs from ``name``. Onboarding already accepts this fact to render
        the Application's ``repoURL``; recording it here is what lets the
        manifest's own readers - the chart's homepage bookmarks among them -
        reach it, since Helm reads the manifest and never the teams/ folder."""
        ...

    def remove_manifest_entry(self, name: str) -> None:
        """Remove the app's entry from whichever role block carries it,
        touching nothing else. A name the manifest does not carry removes
        nothing (existence is the caller's validation)."""
        ...

    def zone(self) -> str:
        """The install's zone from values.yaml (hostnames and MCP URLs derive from it)."""
        ...

    def install(self) -> str:
        """The install's name from foundry.yaml (the deploy-<install> branch apps track)."""
        ...

    def environments(self) -> tuple[str, ...]:
        """The install's declared environments from foundry.yaml, in order; the
        first is the entry environment (the automatically deployed one)."""
        ...

    def tunnel_id(self) -> str:
        """The install's Cloudflare tunnel id from values.yaml (the external-dns target)."""
        ...

    def operators(self) -> tuple[str, ...]:
        """The install's operators from values.yaml (the team RBAC subjects)."""
        ...

    def default_brokers(self) -> tuple[DefaultBroker, ...]:
        """The install's declared default brokers from values.yaml (ADR-045).

        Zero or more, in declaration order; the identity grant splices whatever is
        here into every realm it renders. An install that declares none brokers
        nothing, which is a supported install and not a missing value.
        """
        ...

    def login_theme(self) -> str:
        """The install's Keycloak login theme from values.yaml (identity.loginTheme.name).

        Empty when the branch names none: the realm then keeps Keycloak's own look.
        Named, the identity grant writes it into every realm it renders, and the
        platform chart is what mounts the theme itself.
        """
        ...

    def registry(self) -> InstallRegistry:
        """The install's registry fact from values.yaml (ADR-044, platform #164).

        Undeclared on a branch predating the block (its chart carries ghcr.io
        itself), and callers then fall back to GHCR under the app-repo org. A
        declared registry with an empty pull_secret is the node-identity shape,
        not a missing value.
        """
        ...

    def organisation(self) -> InstallOrganisation:
        """The install's organisation fact from values.yaml (githubOrgUrl,
        platformRepo, ciRepo): where its repositories live.

        Undeclared on a branch predating githubOrgUrl, and callers then fall
        back to the fleet default the studio was built for (APP_REPO_ORG).
        """
        ...

    def team_files(self, name: str) -> tuple[str, ...]:
        """The YAML filenames in teams/<name>/, or () when the app is not onboarded."""
        ...

    def team_file_text(self, name: str, filename: str) -> str | None:
        """The raw teams/<name>/<filename> text, or None when absent."""
        ...

    def write_team_file(self, name: str, filename: str, text: str) -> None:
        """Create or replace teams/<name>/<filename>."""
        ...

    def team_manifest(self, name: str) -> TeamManifest | None:
        """Facts parsed across teams/<name>/*.yaml, or None when not onboarded."""
        ...

    def team_documents(self, name: str) -> tuple[dict, ...]:
        """Every YAML document across teams/<name>/*.yaml, parsed; () when the
        app has no team folder."""
        ...

    def claims(self) -> tuple[IntentClaim, ...]:
        """The conformance claims declared in the platform's intent.yaml."""
        ...

    def raw_read(self, rel_path: str) -> str | None:
        """Read a repo file as text, or None when absent (snapshot support)."""
        ...

    def raw_write(self, rel_path: str, text: str) -> None:
        """Write a repo file as text (restore support)."""
        ...

    def raw_delete(self, rel_path: str) -> None:
        """Delete a repo file if it exists (restore support for created files)."""
        ...
