"""Use case: list the studio's open pull requests."""

from __future__ import annotations

from studio.application.ports.outbound.git_pr import GitPr
from studio.domain.model.pr_info import PrInfo

__all__ = ["ListPrs"]


class ListPrs:
    """Implements ListPrsPort over the git port."""

    def __init__(self, git: GitPr) -> None:
        self._git = git

    def execute(self) -> tuple[PrInfo, ...]:
        return self._git.open_prs()
