"""Mapper: domain OnboardingResult to OnboardingResultResponse DTO."""

from __future__ import annotations

from typing import TYPE_CHECKING

from studio.adapters.inbound.http.dtos.onboarding_result_response import (
    OnboardingResultResponse,
)
from studio.adapters.inbound.http.mappers.conformance_mapper import map_conformance_report
from studio.adapters.inbound.http.mappers.pr_mapper import map_pr_info

if TYPE_CHECKING:
    from studio.domain.model.onboarding_result import OnboardingResult

__all__ = ["map_onboarding_result"]


def map_onboarding_result(result: OnboardingResult) -> OnboardingResultResponse:
    """Convert an onboarding result to its response DTO."""
    return OnboardingResultResponse(
        app=result.app,
        changed_files=list(result.changed_files),
        baseline=map_conformance_report(result.baseline),
        report=map_conformance_report(result.report),
        branch=result.branch,
        pr=map_pr_info(result.pr) if result.pr else None,
    )
