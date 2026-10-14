"""Composition fail-closed: PR-mode refuses to start on missing configuration.

The deployed (PR-mode) studio is selected by STUDIO_PLATFORM_REPO_URL. It must
never fall back to an env-specific default for the deploy branch: a wrong branch
would send this install's onboardings into another install's git history,
silently. So a repo URL without an explicit deploy branch (or without a token)
fails closed at composition, before any git work.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from studio.adapters.outbound.git_noop.noop_git_pr import NoopGitPr
from studio.container import (
    _resolve_git_pr,
    resolve_deploy_branch,
    resolve_platform_root,
)
from studio.domain.exceptions.sync_failed_error import SyncFailedError

_URL = "https://github.com/example/foundry-platform.git"


def test_no_repo_url_is_the_local_noop_composition(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STUDIO_PLATFORM_REPO_URL", raising=False)
    assert isinstance(_resolve_git_pr(Path("."), resolve_deploy_branch()), NoopGitPr)


def test_pr_mode_without_a_deploy_branch_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDIO_PLATFORM_REPO_URL", _URL)
    monkeypatch.delenv("STUDIO_DEPLOY_BRANCH", raising=False)
    with pytest.raises(SyncFailedError, match="STUDIO_DEPLOY_BRANCH"):
        _resolve_git_pr(Path("."), resolve_deploy_branch())


def test_pr_mode_with_a_branch_but_no_token_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDIO_PLATFORM_REPO_URL", _URL)
    monkeypatch.setenv("STUDIO_DEPLOY_BRANCH", "deploy-example")
    monkeypatch.delenv("STUDIO_GITHUB_TOKEN", raising=False)
    with pytest.raises(SyncFailedError, match="STUDIO_GITHUB_TOKEN"):
        _resolve_git_pr(Path("."), resolve_deploy_branch())


def test_deploy_branch_has_no_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STUDIO_DEPLOY_BRANCH", raising=False)
    assert resolve_deploy_branch() is None


def test_the_sibling_clone_is_named_by_the_platform_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fleet that prefixes its repositories clones acme-platform, not foundry-platform."""
    monkeypatch.delenv("STUDIO_PLATFORM_ROOT", raising=False)
    monkeypatch.setenv(
        "STUDIO_PLATFORM_REPO_URL",
        "https://github.com/Some-Fleet/acme-platform.git",
    )
    assert resolve_platform_root().name == "acme-platform"


def test_the_sibling_clone_falls_back_when_nothing_declares_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A workspace declaring neither the root nor the repo URL keeps the
    upstream name: the local no-repo composition never writes, so a wrong guess
    there costs a read, not an install."""
    monkeypatch.delenv("STUDIO_PLATFORM_ROOT", raising=False)
    monkeypatch.delenv("STUDIO_PLATFORM_REPO_URL", raising=False)
    assert resolve_platform_root().name == "foundry-platform"


def test_an_explicit_root_still_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDIO_PLATFORM_ROOT", str(Path("elsewhere") / "checkout"))
    monkeypatch.setenv("STUDIO_PLATFORM_REPO_URL", "https://github.com/x/acme-platform")
    assert resolve_platform_root().name == "checkout"
