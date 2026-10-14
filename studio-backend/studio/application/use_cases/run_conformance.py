"""Use case: run the platform's conformance suite."""

from __future__ import annotations

from studio.application.ports.outbound.conformance_runner import ConformanceRunner
from studio.application.ports.outbound.event_publisher import EventPublisher
from studio.application.services.event_types import CONFORMANCE_COMPLETED, state_fact
from studio.domain.model.conformance_report import ConformanceReport
from studio.logging import get_logger

__all__ = ["RunConformance"]

logger = get_logger(__name__)


class RunConformance:
    """Implements RunConformancePort over the conformance runner."""

    def __init__(self, conformance: ConformanceRunner, events: EventPublisher) -> None:
        self._conformance = conformance
        self._events = events

    def execute(self, *, install: str = "") -> ConformanceReport:
        report = self._conformance.run()
        logger.info(
            "Conformance run: %d passed, %d failed, %d skipped (exit %d)",
            report.passed,
            report.failed,
            report.skipped,
            report.exit_code,
        )
        # The run is finished and its report is in hand before the fact is
        # stated: the causing act is durable first, and the publish cannot
        # change what this returns (REF-Events section 6).
        state_fact(
            self._events,
            event_type=CONFORMANCE_COMPLETED,
            subject=install or "install",
            data={
                "passed": report.passed,
                "failed": report.failed,
                "skipped": report.skipped,
                "verdict": "pass" if report.failed == 0 else "fail",
            },
        )
        return report
