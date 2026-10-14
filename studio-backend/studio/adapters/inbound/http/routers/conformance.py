"""Conformance suite routes."""

from __future__ import annotations

from fastapi import APIRouter

from studio.adapters.inbound.http.dependencies import ContainerDep
from studio.adapters.inbound.http.dtos.conformance_report_response import (
    ConformanceReportResponse,
)
from studio.adapters.inbound.http.mappers.conformance_mapper import map_conformance_report
from studio.adapters.inbound.work import run_serialized

__all__ = ["router"]

router = APIRouter()


@router.post("/conformance/run", response_model=ConformanceReportResponse)
async def run_conformance(container: ContainerDep) -> ConformanceReportResponse:
    """Run the platform's conformance suite and return per-test outcomes."""
    report = await run_serialized(lambda: container.run_conformance().execute())
    return map_conformance_report(report)
