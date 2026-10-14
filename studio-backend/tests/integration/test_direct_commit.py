"""The lifecycle direct commit over a real clone of a real (local, bare) remote.

The studio's clone of the deploy branch is long-lived and the branch moves
under it: the platform repo's CI merges the reconcile, onboarding and
settings pull requests the studio opens. A toggle that edited the clone
while it was behind once reconciled with upstream through a stash, whose pop
conflicted, and committed and pushed teams/<app>/application.yaml carrying the
conflict markers. These tests drive the toggles end to end against a remote
that moved, and against a remote file no commit may carry.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from pytest_intent import intent

from studio.adapters.outbound.git_cli.cli_git_pr import CliGitPr
from studio.adapters.outbound.platform_fs.fs_platform_repository import FsPlatformRepository
from studio.application.use_cases.freeze_promotion import FreezePromotion
from studio.application.use_cases.resume_promotion import ResumePromotion
from studio.domain.exceptions.direct_commit_refused_error import DirectCommitRefusedError
from studio.domain.services.image_promotion import PROMOTION_AUTO
from studio.domain.services.team_documents import (
    freeze_application_promotion,
    pause_application,
)
from tests.conftest import FakeGitPr

_DEPLOY = "deploy-test"
_ALPHA = "teams/alpha-app/application.yaml"
_BETA = "teams/beta-app/application.yaml"
_FREEZE_LINE = 'argocd-image-updater.argoproj.io/app.ignore-tags: "*"'
# The annotation the freeze line sits directly above: an upstream edit to it
# touches the lines a resume removes.
_WRITE_BACK = "argocd-image-updater.argoproj.io/write-back-method: git:secret:argocd/github-creds"


def _git(cwd: Path, *argv: str) -> str:
    proc = subprocess.run(
        ["git", *argv], cwd=cwd, capture_output=True, text=True, encoding="utf-8"
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc.stdout


@pytest.fixture
def upstream(platform_root: Path, tmp_path: Path) -> Path:
    """The platform repo's other writers: a working clone of the bare remote,
    seeded with the synthetic install, both apps frozen."""
    for path in (_ALPHA, _BETA):
        application = platform_root / path
        application.write_text(
            freeze_application_promotion(
                application.read_text(encoding="utf-8"), app=path.split("/")[1]
            ),
            encoding="utf-8",
        )
        assert _FREEZE_LINE in application.read_text(encoding="utf-8")
    # LF throughout, as the platform repo stores it and the studio writes it,
    # so an edit's diff is the edit on every OS.
    for file in platform_root.rglob("*"):
        if file.is_file():
            file.write_bytes(file.read_bytes().replace(b"\r\n", b"\n"))
    bare = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", "-b", _DEPLOY, str(bare))
    _git(platform_root, "init", "-b", _DEPLOY)
    _git(platform_root, "config", "user.name", "platform-ci")
    _git(platform_root, "config", "user.email", "platform-ci@example.test")
    _git(platform_root, "config", "core.autocrlf", "false")
    _git(platform_root, "add", "-A")
    _git(platform_root, "commit", "-m", "chore: seed install")
    _git(platform_root, "remote", "add", "origin", str(bare))
    _git(platform_root, "push", "-u", "origin", _DEPLOY)
    return platform_root


@pytest.fixture
def git(upstream: Path, tmp_path: Path) -> CliGitPr:
    adapter = CliGitPr(
        tmp_path / "clone",
        remote_url=str(tmp_path / "origin.git"),
        token="",
        deploy_branch=_DEPLOY,
        author_name="studio-test",
        author_email="studio-test@example.test",
    )
    adapter.ensure_ready()
    return adapter


def _push_upstream(upstream: Path, path: str, edit: Callable[[str], str]) -> str:
    """Another writer moves the deploy branch: edit ``path`` and push. Returns
    the new remote head."""
    _git(upstream, "pull", "--ff-only")
    target = upstream / path
    target.write_text(edit(target.read_text(encoding="utf-8")), encoding="utf-8", newline="")
    _git(upstream, "commit", "-am", f"chore: upstream edit to {path}")
    _git(upstream, "push", "origin", _DEPLOY)
    return _git(upstream, "rev-parse", "HEAD").strip()


def _remote_head(tmp_path: Path) -> str:
    return _git(tmp_path / "origin.git", "rev-parse", _DEPLOY).strip()


def _remote_file(tmp_path: Path, path: str) -> str:
    return _git(tmp_path / "origin.git", "show", f"{_DEPLOY}:{path}")


def _assert_clone_settled(clone: Path, tmp_path: Path) -> None:
    """The clone sits on the remote head with nothing of the act left over."""
    assert _git(clone, "rev-parse", "HEAD").strip() == _remote_head(tmp_path)
    assert _git(clone, "status", "--porcelain").strip() == ""
    assert _git(clone, "stash", "list").strip() == ""
    assert not (clone / ".git" / "rebase-merge").exists()
    assert not (clone / ".git" / "rebase-apply").exists()


def _rotate_write_back(text: str) -> str:
    assert _WRITE_BACK in text
    return text.replace(_WRITE_BACK, f"{_WRITE_BACK}-rotated")


def _use_cases(clone: Path, git: CliGitPr) -> tuple[FreezePromotion, ResumePromotion]:
    repository = FsPlatformRepository(clone)
    return FreezePromotion(repository, git), ResumePromotion(repository, git)


@intent("INT-LIFECYCLE-003")
def test_resume_over_a_moved_remote_resumes_the_upstream_file(
    upstream: Path, git: CliGitPr, tmp_path: Path
) -> None:
    """INT-LIFECYCLE-003: the clone falls behind and the file the toggle edits
    changes upstream; the toggle reads and edits the upstream file, so the
    remote ends on a clean resumed file, never on conflict markers."""
    clone = tmp_path / "clone"
    _push_upstream(upstream, _ALPHA, _rotate_write_back)
    # The clone is behind: it still carries the file as it was.
    assert "-rotated" not in (clone / _ALPHA).read_text(encoding="utf-8")

    _, resume = _use_cases(clone, git)
    app = resume.execute(name="alpha-app")

    assert app.manifest is not None and app.manifest.promotion == PROMOTION_AUTO
    pushed = _remote_file(tmp_path, _ALPHA)
    assert "<<<<<<<" not in pushed and ">>>>>>>" not in pushed
    yaml.safe_load(pushed)
    assert _FREEZE_LINE not in pushed
    assert f"{_WRITE_BACK}-rotated" in pushed  # the upstream edit survives
    _assert_clone_settled(clone, tmp_path)


@intent("INT-LIFECYCLE-003")
@pytest.mark.parametrize(
    "toggle",
    [
        pytest.param(("pause", pause_application, []), id="pause"),
        pytest.param(
            ("resume", pause_application, ["chore(lifecycle): resume alpha-app"]), id="resume"
        ),
        pytest.param(("promotion/freeze", freeze_application_promotion, []), id="freeze"),
        pytest.param(
            (
                "promotion/resume",
                freeze_application_promotion,
                ["chore(lifecycle): resume promotion for alpha-app"],
            ),
            id="resume-promotion",
        ),
    ],
)
def test_every_toggle_reads_the_refreshed_branch(
    client: TestClient,
    fake_git: FakeGitPr,
    platform_root: Path,
    toggle: tuple[str, Callable[..., str], list[str]],
) -> None:
    """INT-LIFECYCLE-003: every toggle refreshes before it reads. Upstream
    already carries the paused or frozen state the parked checkout lacks, so a
    toggle that read first would act on the wrong state: pause and freeze
    would commit a second time, the resumes would see nothing to resume."""
    route, upstream_state, commits = toggle
    application = platform_root / _ALPHA

    def upstream_moved() -> None:
        text = application.read_text(encoding="utf-8")
        application.write_text(upstream_state(text, app="alpha-app"), encoding="utf-8")

    fake_git.on_refresh = upstream_moved
    response = client.post(f"/api/apps/alpha-app/{route}")
    assert response.status_code == 200, response.text
    assert [c["commit_message"] for c in fake_git.direct_commits] == commits


def _break_spec(text: str) -> str:
    # Far from the annotations a resume edits, so the rebase is clean and only
    # its result is broken.
    assert "    path: prod\n" in text
    return text.replace("    path: prod\n", "    path: [prod\n")


@intent("INT-LIFECYCLE-003")
@pytest.mark.parametrize(
    ("upstream_edit", "reason"),
    [
        pytest.param(_rotate_write_back, "conflicts with this one", id="conflicting-move"),
        pytest.param(_break_spec, "does not parse as YAML", id="clean-rebase-broken-result"),
    ],
)
def test_a_move_between_read_and_commit_is_refused(
    upstream: Path,
    git: CliGitPr,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    upstream_edit: Callable[[str], str],
    reason: str,
) -> None:
    """INT-LIFECYCLE-003: the remote moves again after the toggle read the file.
    A move touching the lines the toggle edits conflicts; one elsewhere rebases
    cleanly but leaves a file that does not parse. Either way the toggle
    refuses, the remote keeps the other writer's head, and the clone is left
    on it, clean."""
    clone = tmp_path / "clone"
    commit = git.commit_to_deploy

    def racing_commit(**kwargs: object) -> None:
        _push_upstream(upstream, _ALPHA, upstream_edit)
        commit(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(git, "commit_to_deploy", racing_commit)
    _, resume = _use_cases(clone, git)
    with pytest.raises(DirectCommitRefusedError, match=reason):
        resume.execute(name="alpha-app")

    upstream_head = _git(upstream, "rev-parse", "HEAD").strip()
    assert _remote_head(tmp_path) == upstream_head
    assert _FREEZE_LINE in _remote_file(tmp_path, _ALPHA)
    _assert_clone_settled(clone, tmp_path)
    assert "<<<<<<<" not in (clone / _ALPHA).read_text(encoding="utf-8")


_CONFLICTED = (
    "<<<<<<< Updated upstream\n"
    f"    {_WRITE_BACK}-rotated\n"
    "=======\n"
    f"    {_WRITE_BACK}\n"
    ">>>>>>> Stashed changes\n"
)


def _leave_markers(text: str) -> str:
    # The shape the defect pushed: the stash pop's markers around the
    # annotation it conflicted on, the freeze line still above them.
    return text.replace(f"    {_WRITE_BACK}\n", _CONFLICTED)


def _break_yaml(text: str) -> str:
    return text.replace("  annotations:\n", "  annotations: [unclosed\n", 1)


@intent("INT-LIFECYCLE-003")
@pytest.mark.parametrize(
    ("breakage", "reason"),
    [
        pytest.param(_leave_markers, "carries conflict markers", id="conflict-markers"),
        pytest.param(_break_yaml, "does not parse as YAML", id="unparseable-yaml"),
    ],
)
def test_a_toggle_never_pushes_unparseable_yaml(
    upstream: Path,
    git: CliGitPr,
    tmp_path: Path,
    breakage: Callable[[str], str],
    reason: str,
) -> None:
    """INT-LIFECYCLE-003: an edit to a file that does not parse as YAML
    (conflict markers included) is refused before any commit; the remote keeps
    its head."""
    clone = tmp_path / "clone"
    head = _push_upstream(upstream, _BETA, breakage)
    _, resume = _use_cases(clone, git)

    with pytest.raises(DirectCommitRefusedError, match=reason):
        resume.execute(name="beta-app")

    assert _remote_head(tmp_path) == head
    _assert_clone_settled(clone, tmp_path)
