"""GitPr no-op for the local run: the operator owns the working tree."""

from __future__ import annotations

from studio.domain.exceptions.entity_not_found_error import EntityNotFoundError
from studio.domain.model.pr_info import PrInfo
from studio.logging import get_logger

__all__ = ["NoopGitPr"]

logger = get_logger(__name__)


class NoopGitPr:
    """Implements GitPr over an operator-owned working tree.

    A gate-passing onboarding stays as uncommitted changes for the operator to
    review and commit themselves; a gate-failing one is byte-restored by the
    use case, so no git-level rollback is needed.
    """

    def commit_to_deploy(self, *, paths: tuple[str, ...], commit_message: str) -> None:
        logger.info("Local run: change left in the working tree (suggested: %s)", commit_message)

    def prepare_branch(self, name: str) -> None:
        logger.info("Local run: onboarding %s in the working tree (no branch)", name)

    def finalize(
        self, *, branch: str, commit_message: str, pr_title: str, pr_body: str
    ) -> PrInfo | None:
        logger.info("Local run: change left in the working tree (suggested: %s)", commit_message)
        return None

    def abort(self, branch: str) -> None:
        return None

    def delete_remote_branch(self, branch: str) -> bool:
        return False

    def open_prs(self) -> tuple[PrInfo, ...]:
        return ()

    def prs_for_branch(self, branch: str) -> tuple[PrInfo, ...]:
        return ()

    def get_pr(self, number: int) -> PrInfo:
        raise EntityNotFoundError("pull request", str(number))

    def refresh(self) -> None:
        return None
