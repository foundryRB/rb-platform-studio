"""Outcome of running the install conformance checks."""

from __future__ import annotations

from dataclasses import dataclass

from studio.domain.model.test_outcome import TestOutcome
from studio.domain.model.test_result import TestResult

__all__ = ["ConformanceReport"]


@dataclass(frozen=True)
class ConformanceReport:
    """Result of one conformance run over the install checkout.

    exit_code 0 means every check passed; 1 means failures; any other code
    is a suite-level error (the runner itself broke) and counts as failing
    regardless of reported rows.
    """

    exit_code: int
    results: tuple[TestResult, ...]
    output: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    @property
    def passed(self) -> int:
        return self._count(TestOutcome.PASSED)

    @property
    def failed(self) -> int:
        return self._count(TestOutcome.FAILED)

    @property
    def skipped(self) -> int:
        return self._count(TestOutcome.SKIPPED)

    @property
    def errors(self) -> int:
        return self._count(TestOutcome.ERROR)

    def failing_ids(self) -> frozenset[str]:
        """Node ids that failed or errored; the unit a gate diff compares."""
        bad = {TestOutcome.FAILED, TestOutcome.ERROR}
        return frozenset(result.node_id for result in self.results if result.outcome in bad)

    def for_app(self, app: str) -> tuple[TestResult, ...]:
        """The per-app slice: parametrized conformance rows carry [<app>]."""
        marker = f"[{app}]"
        return tuple(result for result in self.results if marker in result.node_id)

    def _count(self, outcome: TestOutcome) -> int:
        return sum(1 for result in self.results if result.outcome is outcome)
