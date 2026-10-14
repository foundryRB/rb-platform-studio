"""Status of one evidence-chain link."""

from __future__ import annotations

from enum import StrEnum

__all__ = ["LinkStatus"]


class LinkStatus(StrEnum):
    """Verdict one link of the delivery evidence chain reports.

    ``skipped`` means the link could not be evaluated (its detail always
    names the reason); it is honest, distinguishable from verified, and
    never reads as green.
    """

    OK = "ok"
    FAILED = "failed"
    SKIPPED = "skipped"
    PENDING = "pending"
