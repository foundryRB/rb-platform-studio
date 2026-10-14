"""Response DTO for a conformance run."""

from __future__ import annotations

from pydantic import BaseModel

from studio.adapters.inbound.http.dtos.test_result_response import TestResultResponse

__all__ = ["ConformanceReportResponse"]


class ConformanceReportResponse(BaseModel):
    """Outcome of the platform's conformance suite returned over HTTP."""

    ok: bool
    exit_code: int
    passed: int
    failed: int
    skipped: int
    errors: int
    results: list[TestResultResponse]
    output: str
