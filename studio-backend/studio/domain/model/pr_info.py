"""A pull request the studio opened against the platform repo."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["PrInfo"]


@dataclass(frozen=True)
class PrInfo:
    """Identity and state of one onboarding pull request.

    ``merged`` is the admission signal an onboarding run polls for: the
    platform repo's CI merges the PR (ADR-036), and only ``merged: true``
    means the app is admitted; a closed-not-merged PR is an abandonment.
    """

    number: int
    title: str
    url: str
    branch: str
    state: str
    merged: bool
