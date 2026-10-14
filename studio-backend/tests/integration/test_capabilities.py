"""INT-CAP-001: the studio's onboarding capabilities stay complete and in step."""

from __future__ import annotations

import dataclasses
from pathlib import Path

from fastapi.testclient import TestClient
from pytest_intent import intent

from studio.adapters.inbound.http.app import create_app
from studio.adapters.inbound.mcp.server import build_mcp_server
from studio.container import Container
from studio.domain.model.team_manifest import TeamManifest
from tests.conftest import FakeGitPr, StubConformance, build_container


@intent("INT-CAP-001")
def test_detected_capabilities_are_grantable(
    platform_root: Path, fake_git: FakeGitPr
) -> None:
    """INT-CAP-001: every shared capability the studio DETECTS on a team folder (a
    has_* fact) is one it can also GRANT (an onboard_* use case) on all three
    surfaces: a POST /api/onboard/<cap> route AND an onboard_<cap> MCP tool. A
    capability is never detectable-but-not-grantable, nor wired to one door but not
    another, so teaching the studio a new platform capability cannot be half-done."""
    container = build_container(platform_root, StubConformance(), fake_git)
    client = TestClient(create_app(container))

    detected = {
        field.name[len("has_") :]
        for field in dataclasses.fields(TeamManifest)
        if field.name.startswith("has_")
    }
    granted = {
        name[len("onboard_") :]
        for name in dir(Container)
        # onboard_app admits the app itself; the has_* facts are grants ON an app.
        if name.startswith("onboard_") and name != "onboard_app"
    }
    assert detected == granted, (
        f"studio capability drift: it detects {sorted(detected)} on manifests but grants "
        f"{sorted(granted)}; every shared capability it can see, it must be able to grant, "
        "and vice versa"
    )

    # The REST surface: a POST /api/onboard/<cap> route per grant.
    api_caps = {
        path.rsplit("/", 1)[1]
        for path in client.app.openapi()["paths"]  # type: ignore[attr-defined]
        if "/onboard/" in path
    }
    ungranted_rest = sorted(cap for cap in granted if cap not in api_caps)
    assert not ungranted_rest, f"capabilities missing a POST /onboard/<cap> route: {ungranted_rest}"

    # The MCP surface: an onboard_<cap> tool per grant, so a capability wired to
    # REST but not MCP (the third door) cannot slip through. list_tools() on the
    # server's tool manager is the synchronous accessor for the registered tools.
    mcp_tools = {tool.name for tool in build_mcp_server(container)._tool_manager.list_tools()}
    ungranted_mcp = sorted(cap for cap in granted if f"onboard_{cap}" not in mcp_tools)
    assert not ungranted_mcp, f"capabilities missing an onboard_<cap> MCP tool: {ungranted_mcp}"
