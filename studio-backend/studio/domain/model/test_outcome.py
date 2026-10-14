"""Outcome of one conformance test."""

from __future__ import annotations

from enum import StrEnum

__all__ = ["TestOutcome"]


class TestOutcome(StrEnum):
    """Verdict pytest reported for a single test node."""

    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"
