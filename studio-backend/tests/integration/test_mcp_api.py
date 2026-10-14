"""MCP integration tests: a real server exercised through the protocol client."""

from __future__ import annotations

import socket
import threading
import time
from pathlib import Path
from types import TracebackType

import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from pytest_intent import intent

from studio.adapters.inbound.http.app import create_app
from studio.container import Container
from tests.conftest import (
    FakeGitPr,
    FakeProbe,
    StubConformance,
    build_container,
    failing_report,
    passing_report,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class _Server:
    """Uvicorn on an ephemeral port, running the app for the test's duration."""

    def __init__(self, container: Container) -> None:
        port = _free_port()
        config = uvicorn.Config(
            create_app(container), host="127.0.0.1", port=port, log_level="warning"
        )
        self.base_url = f"http://127.0.0.1:{port}"
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    def __enter__(self) -> _Server:
        self._thread.start()
        deadline = time.monotonic() + 15
        while not self._server.started:
            if time.monotonic() > deadline:
                raise RuntimeError("test server failed to start")
            time.sleep(0.05)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=10)


def _pr_container(platform_root: Path, git: FakeGitPr, failing: bool = False) -> Container:
    reports = [passing_report(), failing_report()] if failing else None
    return build_container(platform_root, StubConformance(reports), git)


async def _tool_names(base_url: str) -> set[str]:
    async with (
        streamable_http_client(f"{base_url}/mcp") as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        tools = await session.list_tools()
        return {tool.name for tool in tools.tools}


class TestMcpSurface:
    @pytest.mark.anyio
    async def test_tools_mirror_inbound_ports(
        self, platform_root: Path, fake_git: FakeGitPr
    ) -> None:
        with _Server(_pr_container(platform_root, fake_git)) as srv:
            names = await _tool_names(srv.base_url)
        assert {
            "list_apps",
            "get_app",
            "pause_app",
            "resume_app",
            "freeze_promotion",
            "resume_promotion",
            "list_claims",
            "list_platform_settings",
            "update_platform_setting",
            "run_conformance",
            "conformance_report",
            "onboard_app",
            "offboard_app",
            "reconcile_app",
            "create_app_repo",
            "onboard_database",
            "onboard_identity",
            "reconcile_identity",
        } <= names

    @intent("INT-MCP-002")
    @pytest.mark.anyio
    async def test_pr_tools_follow_the_capability_wiring(
        self, platform_root: Path, fake_git: FakeGitPr
    ) -> None:
        with _Server(_pr_container(platform_root, fake_git)) as srv:
            managed = await _tool_names(srv.base_url)
        local = build_container(platform_root, StubConformance(), None)
        with _Server(local) as srv:
            operator_owned = await _tool_names(srv.base_url)
        pr_surface = {
            "list_onboarding_prs",
            "get_onboarding_pr",
            "cancel_onboarding",
            "refresh_platform",
        }
        assert pr_surface <= managed
        assert not pr_surface & operator_owned

    @pytest.mark.anyio
    async def test_pause_tool_direct_commits_and_flips_status(
        self, platform_root: Path, fake_git: FakeGitPr
    ) -> None:
        with _Server(_pr_container(platform_root, fake_git)) as srv:
            async with (
                streamable_http_client(f"{srv.base_url}/mcp") as (read, write, _),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                result = await session.call_tool("pause_app", {"name": "alpha-app"})
        assert not result.isError
        assert "paused" in str(result.content)
        assert fake_git.direct_commits[0]["commit_message"] == "chore(lifecycle): pause alpha-app"
        assert fake_git.finalized == []  # the toggle opens no pull request

    @pytest.mark.anyio
    async def test_platform_settings_tool_reads_the_deploy_branch(
        self, platform_root: Path, fake_git: FakeGitPr
    ) -> None:
        # The install's own values file is what the studio's checkout carries;
        # the value asserted below is deliberately one no default and no
        # description string contains, so the read cannot pass on prose.
        (platform_root / "values.yaml").write_text(
            "zone: lab.example.dev\nobservability:\n  logRetention: 336h\n", encoding="utf-8"
        )
        with _Server(_pr_container(platform_root, fake_git)) as srv:
            async with (
                streamable_http_client(f"{srv.base_url}/mcp") as (read, write, _),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                result = await session.call_tool("list_platform_settings", {})
        assert not result.isError
        assert "observability.log-retention" in str(result.content)
        assert "336h" in str(result.content)

    @pytest.mark.anyio
    async def test_settings_write_tool_ships_a_pull_request(
        self, platform_root: Path, fake_git: FakeGitPr
    ) -> None:
        with _Server(_pr_container(platform_root, fake_git)) as srv:
            async with (
                streamable_http_client(f"{srv.base_url}/mcp") as (read, write, _),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                result = await session.call_tool(
                    "update_platform_setting",
                    {"key": "observability.log-retention", "value": "168h"},
                )
                refused = await session.call_tool(
                    "update_platform_setting",
                    {"key": "observability.log-retention", "value": "whenever"},
                )
        assert not result.isError
        assert "values.yaml" in str(result.content)
        assert (platform_root / "values.yaml").read_text(encoding="utf-8").count("168h") == 1
        assert fake_git.finalized[-1]["branch"] == "settings/observability-log-retention"
        # A value the knob's unit does not admit is refused over the protocol too.
        assert refused.isError

    @pytest.mark.anyio
    async def test_read_tool_returns_manifest_facts(
        self, platform_root: Path, fake_git: FakeGitPr
    ) -> None:
        with _Server(_pr_container(platform_root, fake_git)) as srv:
            async with (
                streamable_http_client(f"{srv.base_url}/mcp") as (read, write, _),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                result = await session.call_tool("get_app", {"name": "alpha-app"})
        assert not result.isError
        assert "alpha-app.lab.example.dev" in str(result.content)

    @intent("INT-STATUS-001")
    @pytest.mark.anyio
    async def test_app_status_reports_the_evidence_chain(
        self, platform_root: Path, fake_git: FakeGitPr
    ) -> None:
        """INT-STATUS-001: the evidence-chain read over the protocol answers
        every link typed with the derived stage; the test composition wires
        no app-repo source, so the unreadable legs read skipped with their
        reasons rather than crashing or guessing."""
        with _Server(_pr_container(platform_root, fake_git)) as srv:
            async with (
                streamable_http_client(f"{srv.base_url}/mcp") as (read, write, _),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                result = await session.call_tool("app_status", {"name": "alpha-app"})
        assert not result.isError
        content = str(result.content)
        assert '"stage": "awaiting_first_artifacts"' in content
        assert "alpha-app.lab.example.dev" in content
        for link in (
            "onboarded",
            "onboarding_pr",
            "app_repo",
            "ci",
            "promotion",
            "probe",
            "identity_caveat",
        ):
            assert f'"{link}"' in content
        assert "no app-repo source wired" in content

    @pytest.mark.anyio
    async def test_app_status_unknown_app_is_the_not_found_error(
        self, platform_root: Path, fake_git: FakeGitPr
    ) -> None:
        with _Server(_pr_container(platform_root, fake_git)) as srv:
            async with (
                streamable_http_client(f"{srv.base_url}/mcp") as (read, write, _),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                result = await session.call_tool("app_status", {"name": "no-such-app"})
        assert result.isError
        assert "app not found: no-such-app" in str(result.content)

    @pytest.mark.anyio
    async def test_get_onboarding_pr_reports_merged(
        self, platform_root: Path, fake_git: FakeGitPr
    ) -> None:
        """The merge-status signal an onboarding run polls: a merged PR reads
        merged: true through the tool, distinguishing admission from a PR that
        is merely closed."""
        from studio.domain.model.pr_info import PrInfo

        fake_git.open.append(
            PrInfo(
                number=42,
                title="feat(teams): onboard gamma-app",
                url="https://github.example/test/pulls/42",
                branch="onboard/gamma-app",
                state="closed",
                merged=True,
            )
        )
        with _Server(_pr_container(platform_root, fake_git)) as srv:
            async with (
                streamable_http_client(f"{srv.base_url}/mcp") as (read, write, _),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                result = await session.call_tool("get_onboarding_pr", {"number": 42})
        assert not result.isError
        content = str(result.content)
        assert '"merged": true' in content
        assert '"state": "closed"' in content
        assert "https://github.example/test/pulls/42" in content


class TestMcpGatedWrites:
    @intent("INT-MCP-001")
    @pytest.mark.anyio
    async def test_onboarding_tool_takes_the_identical_gate_path(
        self, platform_root: Path, fake_git: FakeGitPr
    ) -> None:
        with _Server(_pr_container(platform_root, fake_git)) as srv:
            async with (
                streamable_http_client(f"{srv.base_url}/mcp") as (read, write, _),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                result = await session.call_tool(
                    "onboard_app",
                    {
                        "name": "gamma-app",
                        "display_name": "Gamma App",
                        "description": "The gamma application",
                        "icon": "mdi-gamma",
                        "expose_mcp": True,
                    },
                )
        assert not result.isError
        folder = platform_root / "teams" / "gamma-app"
        assert (folder / "application.yaml").is_file()
        assert (folder / "gateway.yaml").is_file()
        assert fake_git.finalized[0]["branch"] == "onboard/gamma-app"
        assert "onboard/gamma-app" in str(result.content)

    @intent("INT-MCP-001")
    @pytest.mark.anyio
    async def test_rejected_onboarding_rolls_back_and_reports(
        self, platform_root: Path, fake_git: FakeGitPr
    ) -> None:
        manifest_before = (platform_root / "foundry.yaml").read_text(encoding="utf-8")
        with _Server(_pr_container(platform_root, fake_git, failing=True)) as srv:
            async with (
                streamable_http_client(f"{srv.base_url}/mcp") as (read, write, _),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                result = await session.call_tool(
                    "onboard_app",
                    {
                        "name": "gamma-app",
                        "display_name": "Gamma App",
                        "description": "The gamma application",
                        "icon": "mdi-gamma",
                        "expose_mcp": False,
                    },
                )
        assert result.isError
        assert "rejected by the conformance gates" in str(result.content)
        manifest_after = (platform_root / "foundry.yaml").read_text(encoding="utf-8")
        assert manifest_after == manifest_before
        assert not (platform_root / "teams" / "gamma-app").exists()
        assert fake_git.finalized == []

    @intent("INT-MCP-001")
    @pytest.mark.anyio
    async def test_database_onboarding_tool_takes_the_identical_gate_path(
        self, platform_root: Path, fake_git: FakeGitPr
    ) -> None:
        with _Server(_pr_container(platform_root, fake_git)) as srv:
            async with (
                streamable_http_client(f"{srv.base_url}/mcp") as (read, write, _),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                result = await session.call_tool("onboard_database", {"name": "alpha-app"})
        assert not result.isError
        jobs = (platform_root / "teams" / "alpha-app" / "jobs.yaml").read_text(
            encoding="utf-8"
        )
        assert "pg-alpha-app-provision" in jobs
        assert fake_git.finalized[0]["branch"] == "onboard/alpha-app-db"
        assert "onboard/alpha-app-db" in str(result.content)

    @intent("INT-MCP-001")
    @pytest.mark.anyio
    async def test_identity_onboarding_tool_takes_the_identical_gate_path(
        self, platform_root: Path, fake_git: FakeGitPr
    ) -> None:
        with _Server(_pr_container(platform_root, fake_git)) as srv:
            async with (
                streamable_http_client(f"{srv.base_url}/mcp") as (read, write, _),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                result = await session.call_tool("onboard_identity", {"name": "alpha-app"})
        assert not result.isError
        config = (platform_root / "teams" / "alpha-app" / "config.yaml").read_text(
            encoding="utf-8"
        )
        assert "keycloak-realm-alpha-app" in config
        assert fake_git.finalized[0]["branch"] == "onboard/alpha-app-identity"
        assert "onboard/alpha-app-identity" in str(result.content)

    @intent("INT-MCP-001")
    @intent("INT-GRANT-010")
    @pytest.mark.anyio
    async def test_identity_reconcile_tool_takes_the_identical_gate_path(
        self, platform_root: Path, fake_git: FakeGitPr
    ) -> None:
        """The realm on the branch was granted under one declaration; the install
        then declares a second broker, and the tool brings the realm up to date on
        the same gate path as the onboarding. Reconciling again is a typed
        refusal, so a sweep can tell "nothing to do" from a failure."""
        values = platform_root / "values.yaml"
        entra = "  - alias: entra\n    providerId: oidc\n    secretRef: keycloak-entra\n"
        values.write_text(values.read_text(encoding="utf-8") + entra, encoding="utf-8")
        with _Server(_pr_container(platform_root, fake_git)) as srv:
            async with (
                streamable_http_client(f"{srv.base_url}/mcp") as (read, write, _),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                result = await session.call_tool("reconcile_identity", {"name": "beta-app"})
                again = await session.call_tool("reconcile_identity", {"name": "beta-app"})
        assert not result.isError
        config = (platform_root / "teams" / "beta-app" / "config.yaml").read_text(
            encoding="utf-8"
        )
        assert "alias: entra" in config
        assert fake_git.finalized[0]["branch"] == "reconcile/beta-app-identity"
        assert "reconcile/beta-app-identity" in str(result.content)
        assert again.isError
        assert "AlreadyExistsError" in str(again.content)
        assert "nothing to reconcile" in str(again.content)
        assert len(fake_git.finalized) == 1


class TestMcpPrompts:
    @intent("INT-SRP-001")
    @pytest.mark.anyio
    async def test_onboard_app_prompt_carries_the_team_side_runbook(
        self, platform_root: Path, fake_git: FakeGitPr
    ) -> None:
        """INT-SRP-001: the team-owned side ships as a runbook the caller executes."""
        with _Server(_pr_container(platform_root, fake_git)) as srv:
            async with (
                streamable_http_client(f"{srv.base_url}/mcp") as (read, write, _),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                prompts = await session.list_prompts()
                names = {prompt.name for prompt in prompts.prompts}
                result = await session.get_prompt("onboard-app", {"app": "gamma-app"})
        assert "onboard-app" in names
        text = str(result.messages[0].content)
        assert "onboard_app" in text  # platform side: the tool, not hand edits
        assert "deploy" in text and "orphan branch" in text  # team side: deploy branch
        assert "lab.example.dev" in text  # parametrized with live install facts
        assert "test-org" in text.lower()  # chart registry derived from the org
        assert "get_onboarding_pr" in text  # the PR composition serves the poll

    @pytest.mark.anyio
    async def test_onboard_app_prompt_matches_the_local_composition(
        self, platform_root: Path
    ) -> None:
        """The runbook names the PR surface only where the composition serves
        it: the local checkout composition leaves the vetted change in the
        working tree with no PR to poll."""
        local = build_container(platform_root, StubConformance(), None)
        with _Server(local) as srv:
            async with (
                streamable_http_client(f"{srv.base_url}/mcp") as (read, write, _),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                result = await session.get_prompt("onboard-app", {"app": "gamma-app"})
        text = str(result.messages[0].content)
        assert "get_onboarding_pr" not in text
        assert "list_onboarding_prs" not in text
        assert "working tree" in text
        assert "no PR to poll" in text

    @pytest.mark.anyio
    async def test_onboard_app_prompt_rejects_invalid_names(
        self, platform_root: Path, fake_git: FakeGitPr
    ) -> None:
        from mcp.shared.exceptions import McpError

        with _Server(_pr_container(platform_root, fake_git)) as srv:
            async with (
                streamable_http_client(f"{srv.base_url}/mcp") as (read, write, _),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                with pytest.raises(McpError):
                    await session.get_prompt("onboard-app", {"app": "Bad_Name"})


class TestMcpDeploymentSurface:
    @pytest.mark.anyio
    async def test_bare_mcp_path_works_with_the_spa_mounted(
        self,
        platform_root: Path,
        fake_git: FakeGitPr,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Clients connect to /mcp (no slash); the SPA mount at / must not swallow it."""
        dist = tmp_path / "dist"
        dist.mkdir()
        (dist / "index.html").write_text("<html>spa</html>", encoding="utf-8")
        monkeypatch.setenv("STUDIO_FRONTEND_DIST", str(dist))
        with _Server(_pr_container(platform_root, fake_git)) as srv:
            names = await _tool_names(srv.base_url)
        assert "list_apps" in names

    @pytest.mark.anyio
    async def test_allowed_hosts_gate_the_transport(
        self,
        platform_root: Path,
        fake_git: FakeGitPr,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A deployment allows its public hostname; other Host values answer 421."""
        import httpx

        initialize = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "probe", "version": "0"},
            },
        }
        headers = {"Accept": "application/json, text/event-stream"}
        monkeypatch.setenv("STUDIO_MCP_ALLOWED_HOSTS", "studio.example.test")
        with _Server(_pr_container(platform_root, fake_git)) as srv:
            async with httpx.AsyncClient() as client:
                wrong_host = await client.post(
                    f"{srv.base_url}/mcp/", json=initialize, headers=headers
                )
                right_host = await client.post(
                    f"{srv.base_url}/mcp/",
                    json=initialize,
                    headers={**headers, "Host": "studio.example.test"},
                )
        assert wrong_host.status_code == 421
        assert right_host.status_code == 200


class TestRefusalsCarryTheirType:
    """MCP flattens an exception to str(e), so a refusal must name its own class.

    The Console branches on which refusal it got - adopt an existing repo,
    degrade when no write credential is wired, refuse outright when a scaffold
    failed halfway - and without the class name it has only prose to match,
    which is not a contract. See _typed_refusal (foundry-console#42 removes the
    need once the internal REST door carries the status itself).
    """

    class _Reader:
        def __init__(self, exists: bool) -> None:
            self._exists = exists

        def deploy_values(self, **kwargs: object) -> None:
            return None

        def repo_exists(self, **kwargs: object) -> bool:
            return self._exists

        def default_branch(self, **kwargs: object) -> None:
            return None

        def file_text(self, **kwargs: object) -> None:
            return None

        def branch_paths(self, **kwargs: object) -> None:
            return None

    class _Writer:
        def __init__(self, *, seeds: bool) -> None:
            self._seeds = seeds

        def create_repository(self, **kwargs: object) -> bool:
            return True

        def delete_repository(self, **kwargs: object) -> bool:
            return True

        def latest_semver_tag(self, **kwargs: object) -> None:
            return None

        def create_orphan_branch(self, **kwargs: object) -> bool:
            return True

        def last_failure(self) -> str:
            return ""

        def seed_branch(self, **kwargs: object) -> bool:
            return self._seeds

    def _container(self, platform_root: Path, *, exists: bool, seeds: bool) -> Container:
        return Container(
            platform_root=platform_root,
            conformance=StubConformance(),
            git_pr=FakeGitPr(),
            http_probe=FakeProbe(),
            app_repo=self._Reader(exists),
            app_writer=self._Writer(seeds=seeds),
        )

    async def _refusal(self, container: Container) -> str:
        with _Server(container) as srv:
            async with (
                streamable_http_client(f"{srv.base_url}/mcp") as (read, write, _),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                result = await session.call_tool(
                    "create_app_repo",
                    {"name": "gamma-app", "display_name": "G", "description": "d"},
                )
        assert result.isError
        return str(result.content)

    @intent("INT-SCAFFOLD-001")
    @pytest.mark.anyio
    async def test_an_existing_repository_names_already_exists(
        self, platform_root: Path
    ) -> None:
        text = await self._refusal(self._container(platform_root, exists=True, seeds=True))
        assert "AlreadyExistsError" in text

    @intent("INT-SCAFFOLD-001")
    @pytest.mark.anyio
    async def test_a_failed_scaffold_names_pr_failed(self, platform_root: Path) -> None:
        text = await self._refusal(self._container(platform_root, exists=False, seeds=False))
        assert "PrFailedError" in text
        assert "was removed" in text  # and still states what happened
