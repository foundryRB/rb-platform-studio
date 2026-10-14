"""Facts parsed from an app's team folder (teams/<app>/ on the install branch)."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["TeamManifest"]


@dataclass(frozen=True)
class TeamManifest:
    """The onboarding facts an app's teams/<app>/ folder fixes."""

    app: str
    hostname: str
    repo_url: str
    target_revision: str
    display_name: str
    description: str
    icon: str
    has_database: bool
    has_identity: bool = False
    has_events: bool = False
    paused: bool = False
    # How the app's images promote: auto, manual (every alias frozen), or none
    # (the Application declares no Image Updater bindings at all).
    promotion: str = "none"
