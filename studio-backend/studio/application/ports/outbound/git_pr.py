"""Outbound port: branch-and-pull-request persistence for the install's checkout."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from studio.domain.model.pr_info import PrInfo

__all__ = ["GitPr"]


@runtime_checkable
class GitPr(Protocol):
    """Prepare, publish, and abandon onboarding branches against the install's
    deploy branch of the platform repo.

    The deploy branch is the installed state ArgoCD reconciles (ADR-032), so
    onboarding changes never commit to it directly: each rides an onboarding
    branch based on the deploy branch, and the pull request's merge is the
    admission act, performed by the platform repo's CI (ADR-036). Lifecycle
    toggles (pause/resume, freeze/resume promotion) are the one exception,
    committed directly to the deploy branch (commit_to_deploy) because they
    admit no app and grant no hostname. The composition root decides the
    implementation: a real adapter over a managed clone (deployed), or a no-op
    over a working tree the operator commits themselves (local run).
    """

    def prepare_branch(self, name: str) -> None:
        """Create and check out `name` from the upstream deploy-branch head."""
        ...

    def commit_to_deploy(self, *, paths: tuple[str, ...], commit_message: str) -> None:
        """Commit `paths` on the deploy branch and push directly.

        The direct-commit fast path for lifecycle toggles: no branch, no pull
        request, no admission PR. The caller refreshed before reading. Raises
        DirectCommitRefusedError, leaving the remote untouched and the clone on
        the upstream head, when the branch moved under the edit in a way that
        conflicts with it, or when a file it would commit carries conflict
        markers or does not parse as YAML; nothing is ever stashed. In the
        local run this is a no-op and the operator commits the working tree
        themselves.
        """
        ...

    def finalize(
        self, *, branch: str, commit_message: str, pr_title: str, pr_body: str
    ) -> PrInfo | None:
        """Commit everything, push the branch, open the PR against the deploy
        branch. None in the local run."""
        ...

    def abort(self, branch: str) -> None:
        """Discard the branch and return the checkout to the deploy branch."""
        ...

    def delete_remote_branch(self, branch: str) -> bool:
        """Delete `branch` on the remote; False when the remote does not carry it.

        The remote half of abandoning a change. finalize() calls it on itself
        when the push lands but the pull request cannot be opened, so the
        remote never carries a branch no pull request tracks; the cancel verb
        calls it to clear one that already got through.
        """
        ...

    def open_prs(self) -> tuple[PrInfo, ...]:
        """Every pull request the studio's gate prepared and left open.

        All four change-branch families, not onboarding's alone: an offboard,
        a reconcile, and a settings write ship pull requests the same way, and
        each needs a surface once the call that opened it has returned.
        """
        ...

    def prs_for_branch(self, branch: str) -> tuple[PrInfo, ...]:
        """Every pull request, of any state, whose head is `branch`.

        Distinguishes the two states a live change branch can be in, which
        call for opposite responses: a pull request references it (in flight,
        or abandoned with its branch outliving it), or none ever did (an
        orphan the remote should not be carrying).
        """
        ...

    def get_pr(self, number: int) -> PrInfo:
        """One pull request by number, with its merge status.

        The merged flag is the admission signal: the platform repo's CI merges
        the PR (ADR-036), and an onboarding run polls this until it reports
        merged rather than merging by hand.
        """
        ...

    def refresh(self) -> None:
        """Bring the checkout to the upstream deploy-branch head.

        Every direct-commit act calls it before it reads or edits a file.
        """
        ...
