"""Outbound port: write delivery scaffolding into an app repo over the repo host."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

__all__ = ["AppRepoWriter"]


@runtime_checkable
class AppRepoWriter(Protocol):
    """Write the team-side delivery artifacts an onboarding can stand up itself.

    Distinct from AppRepoSource on purpose: reading the fleet is one grant
    (contents read, every app repo), writing it is another, and a composition
    without the write credential simply has no writer wired - onboard_app
    then leaves the deploy branch to the runbook exactly as before. Every
    answer is honest about unreadable state: None proves nothing and the
    caller skips the write rather than guessing.
    """

    def last_failure(self) -> str:
        """The host's own words for the most recent refusal, or "".

        Every other answer here is a bare bool, which tells a caller that a
        write failed but never why - and a refusal a caller cannot name comes
        back to the operator as "retry", sending them after the wrong cause.
        A credential missing one scope refuses identically to a network blip
        from the outside; only the host's message separates them, so the
        writer keeps it and the refusal carries it."""
        ...

    def create_repository(self, *, org: str, name: str, description: str) -> bool:
        """Create the private org repository with an initial commit on its
        default branch. Auto-init is part of the contract, not an
        implementation detail: a repository with no commits cannot be written
        through the git-data API at all, so seed_branch's precondition is
        this call's postcondition. False when the host refuses or cannot be
        reached; an already-existing repository is the caller's pre-flight,
        not this call's."""
        ...

    def delete_repository(self, *, org: str, name: str) -> bool:
        """Delete the org repository. The rollback leg: a scaffold that
        cannot finish undoes the repository it created rather than leaving a
        half-built one behind. False when the host refuses (a token without
        delete rights, say), which the caller must report rather than treat
        as a clean rollback."""
        ...

    def latest_semver_tag(self, *, owner: str, package: str) -> str | None:
        """The highest X.Y.Z tag the GHCR container package carries, or None
        when the package or its versions cannot be read (absent, the token
        not granted packages read, host unreachable)."""
        ...

    def create_orphan_branch(
        self, *, repo_url: str, branch: str, files: dict[str, str], message: str
    ) -> bool:
        """Create ``branch`` as an orphan (no parents) carrying exactly
        ``files``. False when the write fails; never overwrites an existing
        branch (the branch's absence is the caller's precondition). Needs a
        repository that already carries history - seeding a virgin repo is
        seed_branch's job, not this one's."""
        ...

    def seed_branch(
        self, *, repo_url: str, branch: str, files: dict[str, str], message: str
    ) -> bool:
        """Replace an EXISTING ``branch``'s content with exactly ``files``,
        parented on its current head. The mirror of create_orphan_branch:
        that one's precondition is a branch that does not exist, this one's
        is a branch that does - which is what a freshly created repository's
        auto-init default branch is. False when the write fails."""
        ...
