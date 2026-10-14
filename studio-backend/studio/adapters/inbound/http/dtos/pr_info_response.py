"""Response DTO for one onboarding pull request."""

from __future__ import annotations

from pydantic import BaseModel

__all__ = ["PrInfoResponse"]


class PrInfoResponse(BaseModel):
    """Identity and state of one onboarding pull request.

    ``merged`` is the admission signal an onboarding run polls for: only
    ``merged: true`` means the platform repo's CI admitted the app (ADR-036);
    a closed-not-merged PR is an abandonment.
    """

    number: int
    title: str
    url: str
    branch: str
    state: str
    merged: bool
