"""Inbound port: create a new app repository pre-templated with the contract."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from studio.domain.model.repo_scaffold_result import RepoScaffoldResult

__all__ = ["CreateAppRepoPort"]


@runtime_checkable
class CreateAppRepoPort(Protocol):
    """Create the org repository and seed it with the walking-skeleton scaffold.

    The repo is born carrying the whole REF-Foundry app-repo contract (the
    thin CI caller, compose, chart, docs, intent stubs, commit hook), so its
    own CI is green from the first push and a non-templated repo simply fails
    conformance and cannot onboard - the contract is the template, the checks
    are the backstop. Also stands up the install's deploy-<install> branch,
    pinned at the 1.0.0 the first push releases, so onboarding finds every
    team-side artifact already in place. No install-side state changes here:
    creating a repo declares nothing in the manifest and grants no hostname;
    onboarding stays its own gated act.
    """

    def execute(
        self, *, name: str, display_name: str, description: str, repo: str = ""
    ) -> RepoScaffoldResult:
        ...
