"""The recovery verb: clearing a change branch no open pull request tracks.

Both venues, because a recovery path that exists in only one is no recovery
for the operator standing in the other.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from pytest_intent import intent

from studio.adapters.inbound.http.app import create_app
from studio.domain.model.pr_info import PrInfo
from tests.conftest import FakeGitPr, StubConformance, build_container
from tests.integration.test_mcp_api import _Server

_ORPHAN = "onboard/shoot4fun"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def wedged(platform_root: Path, fake_git: FakeGitPr) -> TestClient:
    """The live shape the verb exists for: a branch on the remote that no pull
    request ever referenced, left by a publish that pushed and could not open
    one."""
    fake_git.remote_branches.add(_ORPHAN)
    container = build_container(platform_root, StubConformance(), fake_git)
    return TestClient(create_app(container))


def _pr(state: str, merged: bool = False) -> PrInfo:
    return PrInfo(
        number=11,
        title="feat(teams): onboard shoot4fun",
        url="https://github.example/pr/11",
        branch=_ORPHAN,
        state=state,
        merged=merged,
    )


@intent("INT-GATE-005")
def test_cancel_clears_an_orphaned_branch(wedged: TestClient, fake_git: FakeGitPr) -> None:
    """INT-GATE-005: the orphan is cleared off the remote, so the target that it
    wedged is re-runnable from the studio's own surface."""
    res = wedged.post("/api/prs/cancel", json={"branch": _ORPHAN})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body == {"branch": _ORPHAN, "deleted": True, "prs": []}
    assert fake_git.deleted == [_ORPHAN]
    assert _ORPHAN not in fake_git.remote_branches


@intent("INT-GATE-005")
def test_cancel_is_idempotent_on_a_remote_that_carries_nothing(
    wedged: TestClient, fake_git: FakeGitPr
) -> None:
    """A target already clear is the state the caller wanted, not a failure."""
    assert wedged.post("/api/prs/cancel", json={"branch": _ORPHAN}).status_code == 200
    res = wedged.post("/api/prs/cancel", json={"branch": _ORPHAN})
    assert res.status_code == 200, res.text
    assert res.json()["deleted"] is False


@intent("INT-GATE-005")
def test_cancel_refuses_a_branch_outside_the_studios_own(wedged: TestClient) -> None:
    """The install's deploy branch is the datastore ArgoCD reconciles (ADR-032);
    the verb deletes only what the gate prepares."""
    for branch in ("deploy-example", "main", "onboard/../main", "onboard/"):
        res = wedged.post("/api/prs/cancel", json={"branch": branch})
        assert res.status_code == 400, f"{branch}: {res.text}"
        assert res.json()["error"] == "InvalidBranchError"


@intent("INT-GATE-005")
def test_cancel_refuses_a_branch_an_open_pull_request_tracks(
    wedged: TestClient, fake_git: FakeGitPr
) -> None:
    """An open pull request means the change is in flight toward its automated
    merge (ADR-036); deleting its branch would close it unmerged and lose it."""
    fake_git.branch_prs[_ORPHAN] = [_pr("open")]
    res = wedged.post("/api/prs/cancel", json={"branch": _ORPHAN})
    assert res.status_code == 409, res.text
    assert res.json()["error"] == "PendingMergeError"
    assert fake_git.deleted == []
    assert _ORPHAN in fake_git.remote_branches


@intent("INT-GATE-005")
def test_cancel_clears_a_branch_that_outlived_a_closed_pull_request(
    wedged: TestClient, fake_git: FakeGitPr
) -> None:
    """A closed-unmerged pull request is an abandonment: its branch is the
    operator's to clear, and the cancel reports what it found."""
    fake_git.branch_prs[_ORPHAN] = [_pr("closed")]
    res = wedged.post("/api/prs/cancel", json={"branch": _ORPHAN})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["deleted"] is True
    assert [pr["number"] for pr in body["prs"]] == [11]


@intent("INT-GATE-005")
@pytest.mark.anyio
async def test_cancel_tool_clears_the_orphan_over_mcp(
    platform_root: Path, fake_git: FakeGitPr
) -> None:
    """The same verb through the MCP door: the operator recovering from a
    refused onboard_app is standing there, not at the REST surface."""
    fake_git.remote_branches.add(_ORPHAN)
    container = build_container(platform_root, StubConformance(), fake_git)
    with _Server(container) as srv:
        async with (
            streamable_http_client(f"{srv.base_url}/mcp") as (read, write, _),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            result = await session.call_tool("cancel_onboarding", {"branch": _ORPHAN})
    assert not result.isError, str(result.content)
    assert fake_git.deleted == [_ORPHAN]


@intent("INT-GATE-005")
@pytest.mark.anyio
async def test_cancel_tool_refusal_names_its_error_class(
    platform_root: Path, fake_git: FakeGitPr
) -> None:
    """MCP flattens an exception to its message, so the refusal leads with the
    class: the caller branches on in-flight versus not-ours, not on prose."""
    fake_git.remote_branches.add(_ORPHAN)
    fake_git.branch_prs[_ORPHAN] = [_pr("open")]
    container = build_container(platform_root, StubConformance(), fake_git)
    with _Server(container) as srv:
        async with (
            streamable_http_client(f"{srv.base_url}/mcp") as (read, write, _),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            result = await session.call_tool("cancel_onboarding", {"branch": _ORPHAN})
    assert result.isError
    assert "PendingMergeError" in str(result.content)
    assert fake_git.deleted == []
