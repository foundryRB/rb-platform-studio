"""Mapper: domain ConformanceReport to ConformanceReportResponse DTO."""

from __future__ import annotations

from typing import TYPE_CHECKING

from studio.adapters.inbound.http.dtos.conformance_report_response import (
    ConformanceReportResponse,
)
from studio.adapters.inbound.http.dtos.test_result_response import TestResultResponse

if TYPE_CHECKING:
    from studio.domain.model.conformance_report import ConformanceReport

__all__ = ["map_conformance_report"]


def map_conformance_report(report: ConformanceReport) -> ConformanceReportResponse:
    """Convert a conformance report to its response DTO."""
    return ConformanceReportResponse(
        ok=report.ok,
        exit_code=report.exit_code,
        passed=report.passed,
        failed=report.failed,
        skipped=report.skipped,
        errors=report.errors,
        results=[
            TestResultResponse(
                node_id=result.node_id,
                outcome=result.outcome.value,
                detail=result.detail,
            )
            for result in report.results
        ],
        output=report.output,
    )
