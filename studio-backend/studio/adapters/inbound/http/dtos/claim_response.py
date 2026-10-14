"""Response DTO for one conformance claim."""

from __future__ import annotations

from pydantic import BaseModel

__all__ = ["ClaimResponse"]


class ClaimResponse(BaseModel):
    """One intent claim the conformance suite attests."""

    claim_id: str
    summary: str
    status: str
    scope: str
    criticality: str
