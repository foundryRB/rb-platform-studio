"""Use case: cancel a change branch no open pull request tracks."""

from __future__ import annotations

from studio.application.ports.outbound.git_pr import GitPr
from studio.domain.exceptions.invalid_branch_error import InvalidBranchError
from studio.domain.exceptions.pending_merge_error import PendingMergeError
from studio.domain.model.cancelled_change import CancelledChange
from studio.domain.services.change_branch import is_change_branch
from studio.logging import get_logger

__all__ = ["CancelOnboarding"]

logger = get_logger(__name__)


class CancelOnboarding:
    """Implements CancelOnboardingPort: the operator's way out of a wedged target.

    prepare_branch rejects a target whose branch is still live on the remote,
    which is right while a pull request is carrying that change toward its
    automated merge (ADR-036) and wrong once nothing is: the branch then
    blocks every re-run of that target and no other verb touches it. This one
    deletes it, guarded twice over. The name must be a branch the studio's own
    gate prepares, so the install's deploy branch (the datastore ArgoCD
    reconciles, ADR-032) and the platform repo's main are unreachable from
    here. And an open pull request refuses the cancel outright, because
    deleting its branch would close it unmerged and lose the change.

    Deleting a branch the remote does not carry is an idempotent no-op, not a
    failure: a target already clear is the state the caller wanted.
    """

    def __init__(self, git: GitPr) -> None:
        self._git = git

    def execute(self, *, branch: str) -> CancelledChange:
        if not is_change_branch(branch):
            raise InvalidBranchError(branch)
        prs = self._git.prs_for_branch(branch)
        pending = next((pr for pr in prs if pr.state == "open"), None)
        if pending is not None:
            raise PendingMergeError(branch, pending)
        deleted = self._git.delete_remote_branch(branch)
        logger.info(
            "Cancelled %s: %s",
            branch,
            "branch deleted from the remote" if deleted else "the remote carried no such branch",
        )
        return CancelledChange(branch=branch, deleted=deleted, prs=prs)
