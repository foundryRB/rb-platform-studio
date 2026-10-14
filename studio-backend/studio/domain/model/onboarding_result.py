"""Outcome of a gated onboarding: what changed, what the gates said, where it went."""

from __future__ import annotations

from dataclasses import dataclass

from studio.domain.model.conformance_report import ConformanceReport
from studio.domain.model.pr_info import PrInfo

__all__ = ["OnboardingResult"]


@dataclass(frozen=True)
class OnboardingResult:
    """A conformance-gated onboarding that survived its gates.

    In the PR composition the change lives on `branch` behind `pr`; in the
    local composition both are None and the change sits in the working tree
    for the operator to review and commit.
    """

    app: str
    changed_files: tuple[str, ...]
    baseline: ConformanceReport
    report: ConformanceReport
    branch: str | None
    pr: PrInfo | None
