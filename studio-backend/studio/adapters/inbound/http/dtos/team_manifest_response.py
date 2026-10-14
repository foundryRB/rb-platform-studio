"""Response DTO for team-manifest facts."""

from __future__ import annotations

from pydantic import BaseModel

__all__ = ["TeamManifestResponse"]


class TeamManifestResponse(BaseModel):
    """The onboarding facts one team manifest fixes."""

    hostname: str
    repo_url: str
    target_revision: str
    display_name: str
    description: str
    icon: str
    has_database: bool
    has_identity: bool
    has_events: bool = False
    paused: bool
    promotion: str
