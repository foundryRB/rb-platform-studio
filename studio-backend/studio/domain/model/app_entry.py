"""One app entry of the install manifest (foundry.yaml)."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["AppEntry"]


@dataclass(frozen=True)
class AppEntry:
    """A declared app: its name, its manifest role, and its derived MCP endpoint.

    The manifest lists apps under two roles (ADR-032): ``parts`` (the apps the
    Foundry depends on) and ``output`` (the apps it built and runs). An entry
    carrying ``mcp: true`` serves the Model Context Protocol at
    ``https://<name>.<zone>/mcp``; the URL is derived from the install's zone
    at read time, never stored.

    ``display``, ``description``, and ``icon`` are the tile facts every
    manifest-derived view renders from (the homepage tile among them): the
    manifest is their single source, so a view can never drift from it.
    ``description`` is empty on entries written before it moved into the
    manifest; reconcile_app writes it in as each app is reconciled.

    ``repo`` is the GitHub repository the app ships from, and it is a fact
    SEPARATE from ``name`` (INT-SKELETON-001): the name is the namespace, the
    hostname label, the chart and the GHCR package prefix, while the repo is
    where the code lives. They coincide on an install whose repositories are
    named for the apps they hold, and diverge on one whose organisation is
    shared (a prefix per fleet) or whose app was adopted from elsewhere. Empty
    means "not declared, so the same as the name" - which is why every reader
    asks ``repo_name`` rather than this field, and why an entry only carries a
    ``repo:`` line when it actually differs.
    """

    name: str
    mcp_url: str | None = None
    role: str = "output"
    display: str = ""
    description: str = ""
    icon: str = ""
    repo: str = ""

    @property
    def repo_name(self) -> str:
        """The repository this app ships from: the declared one, else the name.

        The single place the default lives, so no caller re-derives it and
        none can forget that an empty ``repo`` means "same as the name"
        rather than "no repository".
        """
        return self.repo or self.name
