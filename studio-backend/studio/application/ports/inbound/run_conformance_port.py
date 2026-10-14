"""Inbound port: run the conformance suite."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from studio.domain.model.conformance_report import ConformanceReport

__all__ = ["RunConformancePort"]


@runtime_checkable
class RunConformancePort(Protocol):
    """Run the platform's conformance suite against the current checkout."""

    def execute(self) -> ConformanceReport:
        ...
