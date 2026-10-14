"""Response DTO for a gate-passing onboarding."""

from __future__ import annotations

from pydantic import BaseModel

from studio.adapters.inbound.http.dtos.conformance_report_response import (
    ConformanceReportResponse,
)
from studio.adapters.inbound.http.dtos.pr_info_response import PrInfoResponse

__all__ = ["OnboardingResultResponse"]


class OnboardingResultResponse(BaseModel):
    """What an onboarding changed, what the gates said, and where it went."""

    app: str
    changed_files: list[str]
    baseline: ConformanceReportResponse
    report: ConformanceReportResponse
    branch: str | None
    pr: PrInfoResponse | None
