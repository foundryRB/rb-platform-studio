"""Response DTO for one registered app."""

from __future__ import annotations

from pydantic import BaseModel

from studio.adapters.inbound.http.dtos.team_manifest_response import TeamManifestResponse

__all__ = ["AppResponse"]


class AppResponse(BaseModel):
    """A manifest entry joined with its team-folder facts, when onboarded.

    ``name`` and ``repo`` are two facts: the name keys everything the platform
    renders (namespace, hostname, chart, packages), the repo names where the
    code lives. ``repo`` is always resolved - the declared value, else the name
    - so a caller never re-derives the default, and it is present even for an
    app declared but not yet onboarded, where ``manifest`` (and so
    ``manifest.repo_url``) is still None.
    """

    name: str
    repo: str
    mcp_url: str | None
    role: str
    manifest: TeamManifestResponse | None
    status: str
    promotion: str
