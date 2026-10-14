"""Inbound port: read one onboarding pull request's merge status."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from studio.domain.model.pr_info import PrInfo

__all__ = ["GetPrPort"]


@runtime_checkable
class GetPrPort(Protocol):
    """Read one onboarding pull request: the merge-status signal a run polls.

    The platform repo's CI performs the merge (ADR-036), so an onboarding run
    polls this until the PR reports merged rather than merging by hand.
    """

    def execute(self, *, number: int) -> PrInfo:
        ...
