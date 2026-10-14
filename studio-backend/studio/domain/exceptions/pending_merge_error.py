"""Raised when a change branch still has an open pull request against it."""

from __future__ import annotations

from studio.domain.exceptions.app_error import AppError
from studio.domain.model.pr_info import PrInfo

__all__ = ["PendingMergeError"]


class PendingMergeError(AppError):
    """The branch is in flight, not wedged: its pull request awaits admission.

    The platform repo's CI merges an onboarding pull request moments after it
    opens (ADR-036), so an open PR means the change is on its way in. Deleting
    its branch would close the PR unmerged and lose the change.
    """

    def __init__(self, branch: str, pr: PrInfo) -> None:
        super().__init__(
            f"cannot cancel {branch}: pull request {pr.url} is open against it and awaits "
            "its automated merge. Poll it until it reports merged, or close it first if "
            "the change is genuinely abandoned"
        )
        self.branch = branch
        self.pr = pr
