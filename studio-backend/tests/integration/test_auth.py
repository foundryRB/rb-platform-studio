"""Auth-gate tests: fail-closed HTTP Basic across /api and the /mcp mount.

Attest the INT-AUTH claims in the repo intent.yaml. `/openapi.json` stands in
for "any gated route": the middleware runs before routing, so requests are
rejected or admitted purely by the gate, independent of business endpoints.
"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pytest_intent import intent

from studio.adapters.inbound.http.app import create_app
from tests.conftest import FakeGitPr, StubConformance, build_container


def _build_client(
    monkeypatch: pytest.MonkeyPatch, platform_root: Path, **env: str
) -> TestClient:
    """A TestClient over a freshly built app with the given auth env (others cleared)."""
    for key in (
        "STUDIO_AUTH_USER",
        "STUDIO_AUTH_PASSWORD",
        "STUDIO_AUTH_DISABLED",
        "STUDIO_AUTH_SCOPE",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    container = build_container(platform_root, StubConformance(), FakeGitPr())
    return TestClient(create_app(container))


def _basic(user: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@intent("INT-AUTH-001")
def test_rejects_without_credentials(
    monkeypatch: pytest.MonkeyPatch, platform_root: Path
) -> None:
    """INT-AUTH-001: configured auth refuses unauthenticated requests on every surface."""
    client = _build_client(
        monkeypatch, platform_root, STUDIO_AUTH_USER="ops", STUDIO_AUTH_PASSWORD="s3cret"
    )
    api = client.get("/openapi.json")
    assert api.status_code == 401
    assert api.headers.get("WWW-Authenticate", "").lower().startswith("basic")
    assert client.post("/mcp", json={}).status_code == 401


@intent("INT-AUTH-002")
def test_accepts_valid_credentials(
    monkeypatch: pytest.MonkeyPatch, platform_root: Path
) -> None:
    """INT-AUTH-002: valid credentials are admitted; a wrong password is refused."""
    client = _build_client(
        monkeypatch, platform_root, STUDIO_AUTH_USER="ops", STUDIO_AUTH_PASSWORD="s3cret"
    )
    assert client.get("/openapi.json", headers=_basic("ops", "s3cret")).status_code == 200
    assert client.get("/openapi.json", headers=_basic("ops", "nope")).status_code == 401


@intent("INT-AUTH-003")
@pytest.mark.parametrize("path", ["/api/health", "/api/health?nonce=1"])
def test_health_is_exempt(
    monkeypatch: pytest.MonkeyPatch, platform_root: Path, path: str
) -> None:
    """INT-AUTH-003: the health endpoint answers without credentials (for probes)."""
    client = _build_client(
        monkeypatch, platform_root, STUDIO_AUTH_USER="ops", STUDIO_AUTH_PASSWORD="s3cret"
    )
    res = client.get(path)
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


@intent("INT-AUTH-004")
def test_fails_closed_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch, platform_root: Path
) -> None:
    """INT-AUTH-004: no credentials and not explicitly disabled -> 503, not open."""
    client = _build_client(monkeypatch, platform_root)
    assert client.get("/openapi.json").status_code == 503
    assert client.post("/mcp", json={}).status_code == 503
    # Health still answers so probes keep working.
    assert client.get("/api/health").status_code == 200


@intent("INT-AUTH-005")
def test_mcp_scope_gates_only_the_machine_door(
    monkeypatch: pytest.MonkeyPatch, platform_root: Path
) -> None:
    """INT-AUTH-005: scope=mcp keeps /mcp Basic-gated while the human surfaces
    serve open for an OIDC reverse proxy in front to gate."""
    client = _build_client(
        monkeypatch,
        platform_root,
        STUDIO_AUTH_USER="ops",
        STUDIO_AUTH_PASSWORD="s3cret",
        STUDIO_AUTH_SCOPE="mcp",
    )
    # Enter the app lifespan so the /mcp transport's session manager is running;
    # the gate decision (before routing) is what these assertions exercise.
    with client:
        # The /mcp machine door stays gated: no credential is refused, a valid one admitted.
        assert client.post("/mcp", json={}).status_code == 401
        admitted = client.post("/mcp", json={}, headers=_basic("ops", "s3cret"))
        assert admitted.status_code not in (401, 503)
        # The human surfaces serve open; oauth2-proxy is their gate in front.
        assert client.get("/openapi.json").status_code == 200


@intent("INT-AUTH-005")
def test_mcp_scope_fails_closed_on_the_machine_door(
    monkeypatch: pytest.MonkeyPatch, platform_root: Path
) -> None:
    """INT-AUTH-005: scope=mcp with no credentials fails the /mcp door closed
    (503) while the human surfaces stay open for the proxy."""
    client = _build_client(monkeypatch, platform_root, STUDIO_AUTH_SCOPE="mcp")
    assert client.post("/mcp", json={}).status_code == 503
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/api/health").status_code == 200


def test_agent_credential_returns_the_basic_pair(
    monkeypatch: pytest.MonkeyPatch, platform_root: Path
) -> None:
    """/api/agent-credential hands the in-app connect menu the base64 HTTP Basic
    pair; behind oauth2-proxy under scope=mcp only an authenticated human reaches it."""
    client = _build_client(
        monkeypatch,
        platform_root,
        STUDIO_AUTH_USER="ops",
        STUDIO_AUTH_PASSWORD="s3cret",
        STUDIO_AUTH_SCOPE="mcp",
    )
    res = client.get("/api/agent-credential")
    assert res.status_code == 200
    assert base64.b64decode(res.json()["credential"]).decode() == "ops:s3cret"


def test_agent_credential_fails_closed_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch, platform_root: Path
) -> None:
    """With no credential configured there is nothing to hand out: 503, never an
    empty or bogus credential."""
    client = _build_client(monkeypatch, platform_root, STUDIO_AUTH_SCOPE="mcp")
    assert client.get("/api/agent-credential").status_code == 503
