"""Use case: refresh the platform checkout from upstream."""

from __future__ import annotations

from studio.application.ports.outbound.git_pr import GitPr
from studio.logging import get_logger

__all__ = ["RefreshContent"]

logger = get_logger(__name__)


class RefreshContent:
    """Implements RefreshContentPort over the git port."""

    def __init__(self, git: GitPr) -> None:
        self._git = git

    def execute(self) -> None:
        self._git.refresh()
        logger.info("Refreshed platform checkout from upstream")
