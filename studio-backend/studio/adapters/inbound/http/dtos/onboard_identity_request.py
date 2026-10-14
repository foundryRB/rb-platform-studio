"""Request DTO for identity (Keycloak realm) onboarding."""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = ["OnboardIdentityRequest"]


class OnboardIdentityRequest(BaseModel):
    """The facts a realm grant needs: whose it is, and whether skipped
    app-side conformance legs are waived (the walking-skeleton bootstrap)."""

    name: str = Field(min_length=1, max_length=63)
    allow_bootstrap: bool = False
