"""Raised when a branch name is not one the studio's gate prepares."""

from __future__ import annotations

from studio.domain.exceptions.app_error import AppError
from studio.domain.services.change_branch import CHANGE_BRANCH_PREFIXES

__all__ = ["InvalidBranchError"]


class InvalidBranchError(AppError):
    """The branch is outside the studio's own: it may not be deleted.

    The studio discards what it created and nothing else. The install's deploy
    branch is the datastore ArgoCD reconciles (ADR-032), so a verb that deletes
    branches refuses every name that is not one the gate prepares.
    """

    def __init__(self, branch: str) -> None:
        super().__init__(
            f"not a studio change branch: {branch} (expected one of "
            f"{', '.join(f'{prefix}<target>' for prefix in CHANGE_BRANCH_PREFIXES)})"
        )
        self.branch = branch
