"""Pull-request routes.

Mounted only when the composition manages the clone (deployed wiring); the
local run's working tree is operator-owned and opens no pull requests.
"""

from __future__ import annotations

from fastapi import APIRouter

from studio.adapters.inbound.http.dependencies import ContainerDep
from studio.adapters.inbound.http.dtos.cancel_onboarding_request import CancelOnboardingRequest
from studio.adapters.inbound.http.dtos.cancelled_change_response import CancelledChangeResponse
from studio.adapters.inbound.http.dtos.pr_info_response import PrInfoResponse
from studio.adapters.inbound.http.mappers.pr_mapper import map_cancelled_change, map_pr_info
from studio.adapters.inbound.work import run_serialized

__all__ = ["router"]

router = APIRouter()


@router.get("/prs", response_model=list[PrInfoResponse])
async def list_prs(container: ContainerDep) -> list[PrInfoResponse]:
    """Every change the studio has open: onboards, offboards, reconciles, settings."""
    return [map_pr_info(pr) for pr in await run_serialized(lambda: container.list_prs().execute())]


@router.get("/prs/{number}", response_model=PrInfoResponse)
async def get_pr(number: int, container: ContainerDep) -> PrInfoResponse:
    """One onboarding pull request's merge status: the poll-until-merged signal."""
    return map_pr_info(await run_serialized(lambda: container.get_pr().execute(number=number)))


@router.post("/prs/cancel", response_model=CancelledChangeResponse)
async def cancel_onboarding(
    request: CancelOnboardingRequest, container: ContainerDep
) -> CancelledChangeResponse:
    """Clear a change branch off the remote that no open pull request tracks."""
    return map_cancelled_change(
        await run_serialized(
            lambda: container.cancel_onboarding().execute(branch=request.branch)
        )
    )
