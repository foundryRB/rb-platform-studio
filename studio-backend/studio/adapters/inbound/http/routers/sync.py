"""Sync routes: upstream refresh.

Mounted only when the composition manages the clone (deployed wiring); the
local run's working tree is operator-owned and has no sync surface.
"""

from __future__ import annotations

from fastapi import APIRouter

from studio.adapters.inbound.http.dependencies import ContainerDep
from studio.adapters.inbound.http.dtos.refresh_response import RefreshResponse
from studio.adapters.inbound.work import run_serialized

__all__ = ["router"]

router = APIRouter()


@router.post("/sync/refresh", response_model=RefreshResponse)
async def refresh_content(container: ContainerDep) -> RefreshResponse:
    """Pull the upstream deploy-branch head into the managed checkout."""
    await run_serialized(container.refresh_content().execute)
    return RefreshResponse(refreshed=True)
