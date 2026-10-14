"""Mapper: domain PlatformApp to AppResponse DTO."""

from __future__ import annotations

from typing import TYPE_CHECKING

from studio.adapters.inbound.http.dtos.app_response import AppResponse
from studio.adapters.inbound.http.dtos.team_manifest_response import TeamManifestResponse

if TYPE_CHECKING:
    from studio.domain.model.platform_app import PlatformApp
    from studio.domain.model.team_manifest import TeamManifest

__all__ = ["map_app"]


def map_app(app: PlatformApp) -> AppResponse:
    """Convert a platform app to its response DTO.

    Tile facts (display, description, icon) prefer the manifest entry - their
    single source once the homepage tiles render from foundry.yaml - and fall
    back to the team folder's route annotations for apps not yet reconciled
    onto that shape."""
    return AppResponse(
        name=app.entry.name,
        repo=app.entry.repo_name,
        mcp_url=app.entry.mcp_url,
        role=app.entry.role,
        manifest=_map_manifest(app) if app.manifest else None,
        status=_status(app.manifest),
        promotion=_promotion(app.manifest),
    )


def _status(manifest: TeamManifest | None) -> str:
    """Fleet status from desired state: unknown until onboarded, then running/paused."""
    if manifest is None:
        return "unknown"
    return "paused" if manifest.paused else "running"


def _promotion(manifest: TeamManifest | None) -> str:
    """How the app takes new versions: unknown until onboarded, then the
    Application's own mode (auto, manual, or none - no bindings at all).

    Orthogonal to status: an app can be running and frozen (holding its
    version), or paused and still promoting (it takes the new tag when it
    resumes), so the two are read and toggled apart.
    """
    if manifest is None:
        return "unknown"
    return manifest.promotion


def _map_manifest(app: PlatformApp) -> TeamManifestResponse:
    manifest = app.manifest
    assert manifest is not None  # guarded by the caller
    return TeamManifestResponse(
        hostname=manifest.hostname,
        repo_url=manifest.repo_url,
        target_revision=manifest.target_revision,
        display_name=app.entry.display or manifest.display_name,
        description=app.entry.description or manifest.description,
        icon=app.entry.icon or manifest.icon,
        has_database=manifest.has_database,
        has_identity=manifest.has_identity,
        has_events=manifest.has_events,
        paused=manifest.paused,
        promotion=manifest.promotion,
    )
