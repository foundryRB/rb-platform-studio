"""Use case: read one onboarding pull request's merge status."""

from __future__ import annotations

from studio.application.ports.outbound.git_pr import GitPr
from studio.domain.model.pr_info import PrInfo

__all__ = ["GetPr"]


class GetPr:
    """Implements GetPrPort over the git port."""

    def __init__(self, git: GitPr) -> None:
        self._git = git

    def execute(self, *, number: int) -> PrInfo:
        return self._git.get_pr(number)
