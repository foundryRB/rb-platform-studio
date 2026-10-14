"""GithubAppRepo tests for the status reads (the REST API faked).

The CI and promotion links of the evidence chain ride these two reads: the
latest completed workflow run on a branch, and the latest commit touching a
path (the Image Updater write-back). Both must map the API's shape into the
domain records and answer None for anything unreadable.
"""

from __future__ import annotations

import pytest

from studio.adapters.outbound.github_repo.github_app_repo import GithubAppRepo
from studio.domain.model.commit_info import CommitInfo
from studio.domain.model.workflow_run import WorkflowRun

_REPO_URL = "https://github.com/Test-Org/alpha-app"


def test_branch_head_reads_requested_revision_not_path_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = GithubAppRepo("token")
    paths = []

    def fake_api(path_template: str, *, repo_url: str) -> dict:
        paths.append(path_template)
        return {"sha": "requested-head"}

    monkeypatch.setattr(repo, "_api_json", fake_api)
    assert repo.branch_head(repo_url=_REPO_URL, branch="deploy-test") == "requested-head"
    assert paths == ["repos/{owner}/{repo}/commits/deploy-test"]
    monkeypatch.setattr(repo, "_api_json", lambda *args, **kwargs: None)
    assert repo.branch_head(repo_url=_REPO_URL, branch="deploy-test") is None
    assert repo.branch_head(repo_url=_REPO_URL, branch="") is None


def test_latest_workflow_run_maps_the_first_completed_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = GithubAppRepo("token")
    seen: dict[str, str] = {}

    def fake_api(path_template: str, *, repo_url: str) -> dict[str, object]:
        seen["path"] = path_template
        return {
            "workflow_runs": [
                {
                    "name": "Build",
                    "conclusion": "success",
                    "html_url": "https://github.example/runs/1",
                    "updated_at": "2026-07-20T11:58:00Z",
                }
            ]
        }

    monkeypatch.setattr(repo, "_api_json", fake_api)
    run = repo.latest_workflow_run(repo_url=_REPO_URL, branch="main")
    assert run == WorkflowRun(
        name="Build",
        conclusion="success",
        url="https://github.example/runs/1",
        completed_at="2026-07-20T11:58:00Z",
    )
    # The one-call query the evidence chain names: newest completed run only.
    assert "actions/runs?" in seen["path"]
    assert "branch=main" in seen["path"]
    assert "status=completed" in seen["path"]
    assert "per_page=1" in seen["path"]


def test_latest_workflow_run_unreadable_or_empty_is_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = GithubAppRepo("token")
    monkeypatch.setattr(repo, "_api_json", lambda path_template, *, repo_url: None)
    assert repo.latest_workflow_run(repo_url=_REPO_URL, branch="main") is None
    monkeypatch.setattr(
        repo, "_api_json", lambda path_template, *, repo_url: {"workflow_runs": []}
    )
    assert repo.latest_workflow_run(repo_url=_REPO_URL, branch="main") is None
    assert repo.latest_workflow_run(repo_url=_REPO_URL, branch="") is None


def test_latest_commit_maps_sha_first_line_and_committer_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = GithubAppRepo("token")
    seen: dict[str, str] = {}

    def fake_api(path_template: str, *, repo_url: str) -> list[dict[str, object]]:
        seen["path"] = path_template
        return [
            {
                "sha": "abc123def4567890abc123def4567890abc123de",
                "commit": {
                    "message": "build: promote alpha-app 1.4.0\n\nwrite-back body",
                    "committer": {"date": "2026-07-20T12:00:00Z"},
                },
            }
        ]

    monkeypatch.setattr(repo, "_api_json", fake_api)
    commit = repo.latest_commit(
        repo_url=_REPO_URL, branch="deploy-test", path="prod/values.yaml"
    )
    assert commit == CommitInfo(
        sha="abc123def4567890abc123def4567890abc123de",
        message="build: promote alpha-app 1.4.0",
        committed_at="2026-07-20T12:00:00Z",
    )
    assert "commits?" in seen["path"]
    assert "sha=deploy-test" in seen["path"]
    assert "path=prod%2Fvalues.yaml" in seen["path"]
    assert "per_page=1" in seen["path"]


def test_latest_commit_unreadable_or_empty_is_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = GithubAppRepo("token")
    monkeypatch.setattr(repo, "_api_json", lambda path_template, *, repo_url: None)
    assert (
        repo.latest_commit(repo_url=_REPO_URL, branch="deploy-test", path="prod/values.yaml")
        is None
    )
    monkeypatch.setattr(repo, "_api_json", lambda path_template, *, repo_url: [])
    assert (
        repo.latest_commit(repo_url=_REPO_URL, branch="deploy-test", path="prod/values.yaml")
        is None
    )
