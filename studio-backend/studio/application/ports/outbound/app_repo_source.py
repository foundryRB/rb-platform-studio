"""Outbound port: read delivery facts off an app repo over the repo host."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from studio.domain.model.commit_info import CommitInfo
from studio.domain.model.workflow_run import WorkflowRun

__all__ = ["AppRepoSource"]


@runtime_checkable
class AppRepoSource(Protocol):
    """Read one app repo's team-owned delivery legs over the repo host.

    The install conformance checks judge facts that live in the app repo,
    outside the platform checkout: the Image Updater bindings against the
    deploy values they write (the entry environment's values on ``deploy-<install>``),
    the CI caller (``.github/workflows/build.yml`` on the default branch)
    against the shared reusable workflow, and the ``deploy-<install>`` branch
    against the env config it must carry. Those legs are team-owned and hosted
    outside the studio's clone, so reading them is an outbound dependency the
    composition root wires: the deployed studio reads them over the repo host,
    and a composition without a source (local runs, tests) reports the
    dependent rows skipped rather than guessed.
    """

    def branch_head(self, *, repo_url: str, branch: str) -> str | None:
        """The requested branch's current commit SHA, or unknown."""
        ...

    def deploy_values(self, *, repo_url: str, branch: str, path: str) -> dict | None:
        """The parsed mapping at ``path`` on ``branch`` of ``repo_url``, or
        None when it cannot be read (repo, branch, or file absent; host
        unreachable; content not a YAML mapping)."""
        ...

    def repo_exists(self, *, repo_url: str) -> bool | None:
        """Whether the repo is visible at all: True when the host serves it,
        False when the host answers that it is not there for this caller
        (absent under that owner, or present and not granted to the token),
        None when the answer proves nothing (host unreachable, credentials
        rejected, URL unparseable).

        Distinct from ``default_branch`` returning None, which collapses all
        three. A definite False is the one repo-level fact worth reporting
        red: every other leg reads through the repo, so without this they all
        report skipped and each names a different artifact to stand up."""
        ...

    def default_branch(self, *, repo_url: str) -> str | None:
        """The repo's default branch name, or None when the repo cannot be
        read at all (absent, private without a granted token, host
        unreachable)."""
        ...

    def file_text(self, *, repo_url: str, branch: str, path: str) -> str | None:
        """The raw text at ``path`` on ``branch`` of ``repo_url``, or None
        when it cannot be read."""
        ...

    def branch_paths(self, *, repo_url: str, branch: str) -> frozenset[str] | None:
        """Every file path ``branch`` carries, or None when the branch cannot
        be read (absent, host unreachable, listing incomplete)."""
        ...

    def latest_workflow_run(self, *, repo_url: str, branch: str) -> WorkflowRun | None:
        """The most recent completed workflow run on ``branch``, or None when
        no completed run exists or the runs cannot be read."""
        ...

    def latest_commit(self, *, repo_url: str, branch: str, path: str) -> CommitInfo | None:
        """The most recent commit on ``branch`` touching ``path`` (e.g. the
        Image Updater write-back on prod values), or None when it cannot be
        read."""
        ...
