"""Platform settings routes: the curated read, and the gated write."""

from __future__ import annotations

from fastapi import APIRouter

from studio.adapters.inbound.http.dependencies import ContainerDep
from studio.adapters.inbound.http.dtos.onboarding_result_response import (
    OnboardingResultResponse,
)
from studio.adapters.inbound.http.dtos.platform_setting_response import (
    PlatformSettingResponse,
)
from studio.adapters.inbound.http.dtos.update_setting_request import UpdateSettingRequest
from studio.adapters.inbound.http.mappers.onboarding_mapper import map_onboarding_result
from studio.adapters.inbound.http.mappers.platform_setting_mapper import (
    map_platform_setting,
)
from studio.adapters.inbound.work import run_serialized

__all__ = ["router"]

router = APIRouter()


@router.get("/settings", response_model=list[PlatformSettingResponse])
async def list_platform_settings(container: ContainerDep) -> list[PlatformSettingResponse]:
    """Every curated platform knob, as the install's deploy branch has it."""
    settings = await run_serialized(lambda: container.list_platform_settings().execute())
    return [map_platform_setting(setting) for setting in settings]


@router.put("/settings/{key}", response_model=OnboardingResultResponse)
async def update_platform_setting(
    key: str, request: UpdateSettingRequest, container: ContainerDep
) -> OnboardingResultResponse:
    """Tune one curated knob; gated, PR-shipped against the install's deploy branch.

    Returns the same gated-change result an onboarding does - the changed
    files, both conformance reports, and the pull request - because it is the
    same act: a conformance-gated write of installed state, admitted by merge
    (ADR-036) rather than applied here.
    """
    return map_onboarding_result(
        await run_serialized(
            lambda: container.update_platform_setting().execute(key=key, value=request.value)
        )
    )
