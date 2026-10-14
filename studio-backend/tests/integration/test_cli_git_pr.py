"""CliGitPr tests against a real local bare remote (the PR API faked).

The remote carries main (the canonical source) plus the install's orphan
deploy branch; the adapter must park on the deploy branch and target every
operation at it, never at main.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import httpx
import pytest
from pytest_intent import intent

from studio.adapters.outbound.git_cli.cli_git_pr import CliGitPr
from studio.domain.exceptions.already_exists_error import AlreadyExistsError
from studio.domain.exceptions.pr_failed_error import PrFailedError

_DEPLOY = "deploy-test"


def _git(cwd: Path, *argv: str) -> str:
    proc = subprocess.run(
        ["git", *argv], cwd=cwd, capture_output=True, text=True, encoding="utf-8"
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc.stdout


@pytest.fixture
def bare_remote(tmp_path: Path) -> Path:
    """A bare origin seeded with main plus the install's orphan deploy branch."""
    bare = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", "-b", "main", str(bare))
    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, "init", "-b", "main")
    _git(seed, "config", "user.name", "seed")
    _git(seed, "config", "user.email", "seed@example.test")
    (seed / "README.md").write_text("# canonical source\n", encoding="utf-8")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-m", "chore: seed main")
    _git(seed, "remote", "add", "origin", str(bare))
    _git(seed, "push", "-u", "origin", "main")
    # The install branch: orphan, carrying only the installed state (ADR-032).
    _git(seed, "checkout", "--orphan", _DEPLOY)
    _git(seed, "rm", "-rf", "--ignore-unmatch", ".")
    (seed / "foundry.yaml").write_text(
        "install: test\nparts: []\noutput:\n- name: alpha-app\n  display: Alpha\n"
        "  icon: mdi-alpha\n",
        encoding="utf-8",
    )
    _git(seed, "add", "-A")
    _git(seed, "commit", "-m", "chore: seed install")
    _git(seed, "push", "-u", "origin", _DEPLOY)
    return bare


@pytest.fixture
def git_pr(bare_remote: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> CliGitPr:
    adapter = CliGitPr(
        tmp_path / "clone",
        remote_url=str(bare_remote),
        token="",
        deploy_branch=_DEPLOY,
        author_name="studio-test",
        author_email="studio-test@example.test",
    )
    calls: list[dict[str, object]] = []

    def fake_api(method: str, path: str, **kwargs: object) -> object:
        calls.append({"method": method, "path": path, **kwargs})
        if method == "GET" and path.endswith("/pulls"):
            return []  # the pulls listing: no pull request references the branch
        return {
            "number": 42,
            "title": "test pr",
            "html_url": "https://github.example/pr/42",
            "state": "open",
        }

    monkeypatch.setattr(adapter, "_api", fake_api)
    monkeypatch.setattr(adapter, "_owner_repo", lambda: ("test-org", "test-repo"))
    adapter.api_calls = calls  # type: ignore[attr-defined]
    adapter.ensure_ready()
    return adapter


def test_ensure_ready_parks_on_the_deploy_branch(git_pr: CliGitPr, tmp_path: Path) -> None:
    clone = tmp_path / "clone"
    assert _git(clone, "rev-parse", "--abbrev-ref", "HEAD").strip() == _DEPLOY
    # The working tree carries the installed state, not the canonical source.
    assert (clone / "foundry.yaml").is_file()
    assert not (clone / "README.md").exists()


def test_finalize_pushes_the_branch_and_bases_the_pr_on_deploy(
    git_pr: CliGitPr, bare_remote: Path, tmp_path: Path
) -> None:
    clone = tmp_path / "clone"
    git_pr.prepare_branch("onboard/gamma-app")
    (clone / "teams" / "gamma-app").mkdir(parents=True, exist_ok=True)
    (clone / "teams" / "gamma-app" / "namespace.yaml").write_text(
        "kind: Namespace\n", encoding="utf-8"
    )
    pr = git_pr.finalize(
        branch="onboard/gamma-app",
        commit_message="feat(teams): onboard gamma-app",
        pr_title="feat(teams): onboard gamma-app",
        pr_body="body",
    )
    assert pr is not None and pr.number == 42 and pr.branch == "onboard/gamma-app"
    # The PR bases against the deploy branch, never main.
    call = git_pr.api_calls[0]  # type: ignore[attr-defined]
    assert call["json"]["base"] == _DEPLOY
    # The branch is on the remote; the local tree is parked back on deploy, clean of it.
    assert "onboard/gamma-app" in _git(bare_remote, "branch")
    assert _git(clone, "rev-parse", "--abbrev-ref", "HEAD").strip() == _DEPLOY
    assert not (clone / "teams" / "gamma-app").exists()


def test_prepare_branches_from_the_deploy_head(git_pr: CliGitPr, tmp_path: Path) -> None:
    clone = tmp_path / "clone"
    git_pr.prepare_branch("onboard/gamma-app")
    assert _git(clone, "rev-parse", "--abbrev-ref", "HEAD").strip() == "onboard/gamma-app"
    # Branched from the deploy head: the installed state is present, main's is not.
    assert (clone / "foundry.yaml").is_file()
    assert not (clone / "README.md").exists()
    assert (
        _git(clone, "rev-parse", "HEAD").strip()
        == _git(clone, "rev-parse", f"origin/{_DEPLOY}").strip()
    )


def test_prepare_rejects_a_branch_already_on_the_remote(git_pr: CliGitPr) -> None:
    with pytest.raises(AlreadyExistsError):
        git_pr.prepare_branch(_DEPLOY)


def test_get_pr_reports_merged_for_a_merged_pr(
    git_pr: CliGitPr, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The merge-status signal: GET /pulls/{number} carries the explicit merged
    boolean, and the adapter maps it (with state) so an onboarding run can poll
    admission apart from abandonment (both read state=closed)."""
    calls: list[dict[str, object]] = []

    def merged_api(method: str, path: str, **kwargs: object) -> dict[str, object]:
        calls.append({"method": method, "path": path, **kwargs})
        return {
            "number": 42,
            "title": "feat(teams): onboard gamma-app",
            "html_url": "https://github.example/pr/42",
            "state": "closed",
            "merged": True,
            "head": {"ref": "onboard/gamma-app"},
        }

    monkeypatch.setattr(git_pr, "_api", merged_api)
    pr = git_pr.get_pr(42)
    assert calls == [{"method": "GET", "path": "/repos/test-org/test-repo/pulls/42"}]
    assert pr.number == 42
    assert pr.state == "closed"
    assert pr.merged is True
    assert pr.branch == "onboard/gamma-app"


@intent("INT-GATE-003")
def test_prepare_reonboards_after_an_abandoned_remote_branch_was_deleted(
    git_pr: CliGitPr, bare_remote: Path, tmp_path: Path
) -> None:
    """INT-GATE-003: an abandoned onboarding (PR closed, remote branch deleted)
    must not wedge a re-onboard of the same target. A plain fetch leaves a stale
    origin/<name> ref that the pending-onboarding guard false-positives on; the
    prune keeps the guard honest so only a still-live remote branch rejects."""
    clone = tmp_path / "clone"
    # First onboarding: the branch reaches the remote (as finalize pushes it).
    git_pr.prepare_branch("onboard/gamma-app")
    (clone / "teams").mkdir(exist_ok=True)
    (clone / "teams" / "gamma.yaml").write_text("kind: Namespace\n", encoding="utf-8")
    git_pr.finalize(
        branch="onboard/gamma-app",
        commit_message="feat(teams): onboard gamma-app",
        pr_title="feat(teams): onboard gamma-app",
        pr_body="body",
    )
    # The maintainer abandons it: the PR is closed and its remote branch deleted,
    # leaving the studio's checkout holding a now-stale origin/onboard/gamma-app.
    _git(bare_remote, "branch", "-D", "onboard/gamma-app")
    # Re-onboarding the same target must succeed rather than raise AlreadyExistsError.
    git_pr.prepare_branch("onboard/gamma-app")
    assert _git(clone, "rev-parse", "--abbrev-ref", "HEAD").strip() == "onboard/gamma-app"


def _stage_a_change(clone: Path, name: str) -> None:
    (clone / "teams").mkdir(exist_ok=True)
    (clone / "teams" / f"{name}.yaml").write_text("kind: Namespace\n", encoding="utf-8")


@intent("INT-GATE-004")
def test_finalize_deletes_the_pushed_branch_when_the_pr_cannot_be_opened(
    git_pr: CliGitPr, bare_remote: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """INT-GATE-004: publishing is two writes against two systems. When the push
    lands and the pull-request call fails, the branch is deleted again: a branch
    on the remote that no pull request tracks is invisible to every read the
    studio offers while still tripping the pending-onboarding guard, so it would
    wedge that target forever."""
    clone = tmp_path / "clone"
    git_pr.prepare_branch("onboard/gamma-app")
    _stage_a_change(clone, "gamma")

    def failing_api(method: str, path: str, **kwargs: object) -> object:
        if method == "POST":
            raise PrFailedError("GitHub API POST /pulls answered 502: bad gateway")
        return []

    monkeypatch.setattr(git_pr, "_api", failing_api)
    with pytest.raises(PrFailedError):
        git_pr.finalize(
            branch="onboard/gamma-app",
            commit_message="feat(teams): onboard gamma-app",
            pr_title="feat(teams): onboard gamma-app",
            pr_body="body",
        )
    assert "onboard/gamma-app" not in _git(bare_remote, "branch")
    assert _git(clone, "rev-parse", "--abbrev-ref", "HEAD").strip() == _DEPLOY
    # The target is re-runnable, which is the whole point of not leaving it there.
    git_pr.prepare_branch("onboard/gamma-app")


@intent("INT-GATE-004")
def test_delete_remote_branch_reports_whether_the_remote_carried_it(
    git_pr: CliGitPr, bare_remote: Path, tmp_path: Path
) -> None:
    """The remote's own answer, not a stale local ref's: True the first time,
    False once the branch is gone, so a repeat is a no-op rather than a failure."""
    clone = tmp_path / "clone"
    git_pr.prepare_branch("onboard/delta-app")
    _stage_a_change(clone, "delta")
    git_pr.finalize(
        branch="onboard/delta-app",
        commit_message="feat(teams): onboard delta-app",
        pr_title="feat(teams): onboard delta-app",
        pr_body="body",
    )
    assert git_pr.delete_remote_branch("onboard/delta-app") is True
    assert "onboard/delta-app" not in _git(bare_remote, "branch")
    assert git_pr.delete_remote_branch("onboard/delta-app") is False


def test_prepare_names_the_orphan_when_no_pr_references_the_branch(
    git_pr: CliGitPr, tmp_path: Path
) -> None:
    """A live branch is either in flight or orphaned, and the responses are
    opposite, so the refusal says which rather than leaving the operator to guess."""
    clone = tmp_path / "clone"
    git_pr.prepare_branch("onboard/gamma-app")
    _stage_a_change(clone, "gamma")
    git_pr.finalize(
        branch="onboard/gamma-app",
        commit_message="feat(teams): onboard gamma-app",
        pr_title="feat(teams): onboard gamma-app",
        pr_body="body",
    )
    with pytest.raises(AlreadyExistsError) as excinfo:
        git_pr.prepare_branch("onboard/gamma-app")
    message = str(excinfo.value)
    assert "no pull request references it" in message
    assert "cancel_onboarding onboard/gamma-app" in message


def test_prepare_names_the_open_pr_when_one_tracks_the_branch(
    git_pr: CliGitPr, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clone = tmp_path / "clone"
    git_pr.prepare_branch("onboard/gamma-app")
    _stage_a_change(clone, "gamma")
    git_pr.finalize(
        branch="onboard/gamma-app",
        commit_message="feat(teams): onboard gamma-app",
        pr_title="feat(teams): onboard gamma-app",
        pr_body="body",
    )

    def tracked_api(method: str, path: str, **kwargs: object) -> object:
        return [
            {
                "number": 42,
                "title": "feat(teams): onboard gamma-app",
                "html_url": "https://github.example/pr/42",
                "state": "open",
                "head": {"ref": "onboard/gamma-app"},
            }
        ]

    monkeypatch.setattr(git_pr, "_api", tracked_api)
    with pytest.raises(AlreadyExistsError) as excinfo:
        git_pr.prepare_branch("onboard/gamma-app")
    message = str(excinfo.value)
    assert "https://github.example/pr/42 is open against it" in message
    assert "cancel_onboarding" not in message


def test_open_prs_covers_every_change_family_and_nothing_else(
    git_pr: CliGitPr, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every act the gate prepares ships a pull request, and this read is their
    only surface once the call that opened them returned. A human's own pull
    request against the platform repo is not the studio's work and stays out."""
    branches = [
        "onboard/gamma-app",
        "onboard/gamma-app-db",
        "onboard/gamma-app-identity",
        "offboard/delta-app",
        "reconcile/alpha-app",
        "settings/observability-logretention",
        "chore/a-human-edit",
    ]
    monkeypatch.setattr(
        git_pr,
        "_api",
        lambda method, path, **kwargs: [
            {
                "number": index,
                "title": f"change {index}",
                "html_url": f"https://github.example/pr/{index}",
                "state": "open",
                "head": {"ref": ref},
            }
            for index, ref in enumerate(branches)
        ],
    )
    assert [pr.branch for pr in git_pr.open_prs()] == branches[:-1]


def test_abort_discards_the_branch_and_its_changes(
    git_pr: CliGitPr, tmp_path: Path
) -> None:
    clone = tmp_path / "clone"
    git_pr.prepare_branch("onboard/delta-app")
    (clone / "stray.txt").write_text("must not survive", encoding="utf-8")
    git_pr.abort("onboard/delta-app")
    assert _git(clone, "rev-parse", "--abbrev-ref", "HEAD").strip() == _DEPLOY
    assert "onboard/delta-app" not in _git(clone, "branch")


def _advance_origin(bare_remote: Path, tmp_path: Path) -> None:
    """Push an unrelated commit to the origin deploy branch so a parked clone
    falls behind (Image Updater write-backs, other lifecycle commits)."""
    other = tmp_path / "other"
    _git(tmp_path, "clone", "--branch", _DEPLOY, str(bare_remote), str(other))
    _git(other, "config", "user.name", "other")
    _git(other, "config", "user.email", "other@example.test")
    (other / "UPSTREAM.txt").write_text("advanced\n", encoding="utf-8")
    _git(other, "add", "-A")
    _git(other, "commit", "-m", "chore: upstream advance")
    _git(other, "push", "origin", _DEPLOY)


def test_commit_to_deploy_commits_over_an_upstream_advance(
    git_pr: CliGitPr, bare_remote: Path, tmp_path: Path
) -> None:
    """The lifecycle fast path: the edit is written unstaged, committed, rebased
    onto an upstream advance and pushed, with nothing stashed on the way."""
    clone = tmp_path / "clone"
    # The use cases write the edit to the working tree UNSTAGED first.
    (clone / "foundry.yaml").write_text(
        "install: test\nparts: []\noutput:\n- name: alpha-app\n  display: Alpha\n"
        "  icon: mdi-alpha\n- name: beta-app\n  display: Beta\n  icon: mdi-beta\n",
        encoding="utf-8",
    )
    # Meanwhile the origin deploy branch moves.
    _advance_origin(bare_remote, tmp_path)

    git_pr.commit_to_deploy(
        paths=("foundry.yaml",),
        commit_message="chore(lifecycle): pause beta-app",
    )

    assert _git(clone, "rev-parse", "--abbrev-ref", "HEAD").strip() == _DEPLOY
    assert _git(clone, "status", "--porcelain").strip() == ""  # clean tree, nothing dropped
    assert _git(clone, "stash", "list").strip() == ""  # nothing stashed, nothing left behind
    log = _git(clone, "log", "--oneline")
    assert "chore(lifecycle): pause beta-app" in log
    assert "chore: upstream advance" in log  # rebased on top of the advance
    assert (clone / "UPSTREAM.txt").exists()
    # The commit reached the origin deploy branch.
    verify = tmp_path / "verify"
    _git(tmp_path, "clone", "--branch", _DEPLOY, str(bare_remote), str(verify))
    assert "beta-app" in (verify / "foundry.yaml").read_text(encoding="utf-8")


def test_commit_to_deploy_is_a_no_op_when_nothing_changed(
    git_pr: CliGitPr, tmp_path: Path
) -> None:
    clone = tmp_path / "clone"
    before = _git(clone, "rev-parse", "HEAD").strip()
    git_pr.commit_to_deploy(
        paths=("foundry.yaml",),
        commit_message="chore(lifecycle): resume alpha-app",
    )
    assert _git(clone, "rev-parse", "HEAD").strip() == before  # a genuine no-op: no commit


def _github_adapter(tmp_path: Path) -> CliGitPr:
    """An adapter pointed at a github.com remote so _owner_repo resolves. These
    tests drive the API layer and the readers above it, never git, so the clone
    is never provisioned."""
    return CliGitPr(
        tmp_path / "api-only",
        remote_url="https://github.com/an-owner/a-repo.git",
        token="t",
        deploy_branch=_DEPLOY,
        author_name="studio-test",
        author_email="studio-test@example.test",
    )


@intent("INT-STATUS-001")
def test_open_prs_refuses_an_object_where_the_pull_request_array_belongs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """INT-STATUS-001: a skipped link names the reason it could not be evaluated.
    A transferred repository answers 301 with a JSON OBJECT rather than the
    pull-request array; iterated, its keys are strings and the first field access
    died as "string indices must be integers, not 'str'". That named neither the
    repository nor the redirect, and it was what every app_status call reported
    for onboarding_pr."""
    adapter = _github_adapter(tmp_path)
    moved = {
        "message": "Moved Permanently",
        "url": "https://api.github.com/repositories/1240919153/pulls?state=open",
    }
    monkeypatch.setattr(adapter, "_api", lambda *args, **kwargs: moved)
    with pytest.raises(PrFailedError) as failure:
        adapter.open_prs()
    assert "dict" in str(failure.value)
    assert "Moved Permanently" in str(failure.value)


@intent("INT-STATUS-001")
def test_a_read_follows_a_redirect_so_a_renamed_repo_still_answers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rename or transfer must not blind the status read: GitHub's own 301 body
    advises following the redirect, so a read does."""
    adapter = _github_adapter(tmp_path)
    seen: dict[str, object] = {}

    def request(method: str, url: str, **kwargs: object) -> httpx.Response:
        seen["follow_redirects"] = kwargs["follow_redirects"]
        return httpx.Response(200, json=[], request=httpx.Request(method, url))

    monkeypatch.setattr(httpx, "request", request)
    assert adapter.open_prs() == ()
    assert seen["follow_redirects"] is True


@intent("INT-GATE-004")
def test_a_write_refuses_a_redirect_rather_than_following_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """INT-GATE-004: publishing must never look like it worked when it did not.
    httpx demotes a redirected write to GET, so a followed POST would fetch the
    pull-request collection instead of opening anything and answer with something
    plausible - leaving a pushed branch no pull request tracks. The write refuses
    and names the Location, so the stale remote URL is the finding."""
    adapter = _github_adapter(tmp_path)

    def request(method: str, url: str, **kwargs: object) -> httpx.Response:
        assert kwargs["follow_redirects"] is False
        return httpx.Response(
            301,
            json={"message": "Moved Permanently"},
            headers={"location": "https://api.github.com/repositories/1240919153/pulls"},
            request=httpx.Request(method, url),
        )

    monkeypatch.setattr(httpx, "request", request)
    with pytest.raises(PrFailedError) as failure:
        adapter._api("POST", "/repos/an-owner/a-repo/pulls", json={"title": "x"})
    assert "301" in str(failure.value)
    assert "repositories/1240919153" in str(failure.value)


@intent("INT-GATE-004")
def test_a_write_follows_a_method_preserving_redirect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """307 and 308 preserve the method and body by definition, which is why
    GitHub answers a transferred repository's write with one. Refusing them made
    every studio write against a stale remote URL impossible when the redirect
    was the one kind that was always safe to follow; an offboarding could not
    open its pull request at all."""
    adapter = _github_adapter(tmp_path)
    seen: list[tuple[str, str]] = []

    def request(method: str, url: str, **kwargs: object) -> httpx.Response:
        seen.append((method, url))
        if len(seen) == 1:
            return httpx.Response(
                307,
                json={"message": "Moved Permanently"},
                headers={"location": "https://api.github.com/repositories/99/pulls"},
                request=httpx.Request(method, url),
            )
        return httpx.Response(201, json={"number": 7}, request=httpx.Request(method, url))

    monkeypatch.setattr(httpx, "request", request)
    assert adapter._api("POST", "/repos/an-owner/a-repo/pulls", json={"title": "x"}) == {
        "number": 7
    }
    # Followed once, with POST preserved both times - never demoted to GET.
    assert [m for m, _ in seen] == ["POST", "POST"]
    assert seen[1][1] == "https://api.github.com/repositories/99/pulls"


@intent("INT-GATE-004")
def test_a_redirect_off_the_api_origin_never_receives_the_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every request carries a Bearer token. A 307 is followed only back to the
    API's own origin, so a redirect pointing anywhere else is refused rather
    than handed the credential."""
    adapter = _github_adapter(tmp_path)
    calls: list[str] = []

    def request(method: str, url: str, **kwargs: object) -> httpx.Response:
        calls.append(url)
        return httpx.Response(
            307,
            json={"message": "Moved"},
            headers={"location": "https://attacker.example/pulls"},
            request=httpx.Request(method, url),
        )

    monkeypatch.setattr(httpx, "request", request)
    with pytest.raises(PrFailedError) as failure:
        adapter._api("POST", "/repos/an-owner/a-repo/pulls", json={"title": "x"})
    assert "attacker.example" in str(failure.value)
    assert calls == ["https://api.github.com/repos/an-owner/a-repo/pulls"]
