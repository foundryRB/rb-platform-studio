"""Request DTO for cancelling a wedged change branch."""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = ["CancelOnboardingRequest"]


class CancelOnboardingRequest(BaseModel):
    """The branch to clear off the remote.

    Named in full (``onboard/<app>``, ``onboard/<app>-db``,
    ``offboard/<app>``, ``reconcile/<app>``, ``settings/<key>``), exactly as
    the refusal that blocked the re-run reported it.
    """

    branch: str = Field(min_length=1, max_length=255)
