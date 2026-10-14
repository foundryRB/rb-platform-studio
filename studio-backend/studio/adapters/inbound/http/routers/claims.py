"""Conformance claim routes."""

from __future__ import annotations

from fastapi import APIRouter

from studio.adapters.inbound.http.dependencies import ContainerDep
from studio.adapters.inbound.http.dtos.claim_response import ClaimResponse
from studio.adapters.inbound.http.mappers.claim_mapper import map_claim
from studio.adapters.inbound.work import run_serialized

__all__ = ["router"]

router = APIRouter()


@router.get("/claims", response_model=list[ClaimResponse])
async def list_claims(container: ContainerDep) -> list[ClaimResponse]:
    """Every conformance claim the platform's intent.yaml declares."""
    claims = await run_serialized(lambda: container.list_claims().execute())
    return [map_claim(claim) for claim in claims]
