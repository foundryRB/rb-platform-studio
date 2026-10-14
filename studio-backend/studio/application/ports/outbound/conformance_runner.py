"""Outbound port: run the install conformance checks."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from studio.domain.model.conformance_report import ConformanceReport

__all__ = ["ConformanceRunner"]


@runtime_checkable
class ConformanceRunner(Protocol):
    """Validate the installed state the checkout carries (the candidate
    working tree during a gated change)."""

    def run(self) -> ConformanceReport:
        """Run every check and report per-check outcomes."""
        ...
