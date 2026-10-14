"""Mapper: domain IntentClaim to ClaimResponse DTO."""

from __future__ import annotations

from typing import TYPE_CHECKING

from studio.adapters.inbound.http.dtos.claim_response import ClaimResponse

if TYPE_CHECKING:
    from studio.domain.model.intent_claim import IntentClaim

__all__ = ["map_claim"]


def map_claim(claim: IntentClaim) -> ClaimResponse:
    """Convert an intent claim to its response DTO."""
    return ClaimResponse(
        claim_id=claim.claim_id,
        summary=claim.summary,
        status=claim.status,
        scope=claim.scope,
        criticality=claim.criticality,
    )
