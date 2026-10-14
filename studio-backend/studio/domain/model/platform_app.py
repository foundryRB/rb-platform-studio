"""An app as the install knows it: manifest entry plus team-folder facts."""

from __future__ import annotations

from dataclasses import dataclass

from studio.domain.model.app_entry import AppEntry
from studio.domain.model.team_manifest import TeamManifest

__all__ = ["PlatformApp"]


@dataclass(frozen=True)
class PlatformApp:
    """A declared app joined with its team-folder facts, when onboarded.

    The manifest (foundry.yaml) and teams/ are kept in bijection by
    conformance; a missing folder is a half-onboarded state the report
    surfaces.
    """

    entry: AppEntry
    manifest: TeamManifest | None
