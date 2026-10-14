"""Raised when an onboarding fails the platform's conformance gates."""

from __future__ import annotations

from studio.domain.exceptions.app_error import AppError
from studio.domain.model.conformance_report import ConformanceReport

__all__ = ["ValidationFailedError"]


class ValidationFailedError(AppError):
    """The onboarding was rolled back: it introduced new conformance failures."""

    def __init__(self, report: ConformanceReport, new_failures: tuple[str, ...]) -> None:
        details = {
            result.node_id: result.detail for result in report.results if result.detail
        }
        failures = ", ".join(
            f"{node_id} ({details[node_id]})" if node_id in details else node_id
            for node_id in new_failures
        )
        super().__init__("conformance gates failed; onboarding rolled back: " + failures)
        self.report = report
        self.new_failures = new_failures
