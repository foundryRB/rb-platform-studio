"""The deploy-branch bootstrap: onboard_app stands up deploy-<install> itself.

With a fleet reader (the branch's absence) and a fleet writer (the write
credential) wired, the onboarding renders the four env-config files
deterministically - the latest published chart pin, the latest image tag per
released package - and creates the orphan branch. Anything unreadable leaves
the branch to the runbook, and an existing branch is never touched.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from studio.adapters.inbound.http.app import create_app
from studio.container import Container
from studio.domain.services.deploy_branch import render_deploy_branch
from tests.conftest import FakeGitPr, FakeProbe, StubConformance


class _Reader:
    """AppRepoSource stub for the bootstrap: only branch_paths matters here."""

    def __init__(self, branch_paths: frozenset[str] | None = None) -> None:
        self._branch_paths = branch_paths

    def deploy_values(self, *, repo_url: str, branch: str, path: str) -> dict | None:
        return None

    def repo_exists(self, *, repo_url: str) -> bool | None:
        return True

    def default_branch(self, *, repo_url: str) -> str | None:
        return "main"

    def file_text(self, *, repo_url: str, branch: str, path: str) -> str | None:
        return None

    def branch_paths(self, *, repo_url: str, branch: str) -> frozenset[str] | None:
        return self._branch_paths


class _Writer:
    """AppRepoWriter stub: canned GHCR tags, recorded branch creations."""

    def __init__(self, tags: dict[str, str] | None = None) -> None:
        self.tags = tags or {}
        self.created: list[dict[str, object]] = []

    def latest_semver_tag(self, *, owner: str, package: str) -> str | None:
        return self.tags.get(package)

    def create_orphan_branch(
        self, *, repo_url: str, branch: str, files: dict[str, str], message: str
    ) -> bool:
        self.created.append(
            {"repo_url": repo_url, "branch": branch, "files": files, "message": message}
        )
        return True


def _client(
    platform_root: Path,
    fake_git: FakeGitPr,
    reader: _Reader,
    writer: _Writer,
) -> TestClient:
    container = Container(
        platform_root=platform_root,
        conformance=StubConformance(),
        git_pr=fake_git,
        http_probe=FakeProbe(),
        app_repo=reader,
        app_writer=writer,
    )
    return TestClient(create_app(container))


_ONBOARD = {
    "name": "gamma-app",
    "display_name": "Gamma App",
    "description": "The gamma application",
    "icon": "mdi-gamma",
    "image_components": ["server", "docs"],
}


class TestDeployBranchBootstrap:
    def test_onboarding_stands_up_the_absent_branch(
        self, platform_root: Path, fake_git: FakeGitPr
    ) -> None:
        writer = _Writer(
            {
                "charts/gamma-app": "1.2.0",
                "gamma-app-server": "1.4.2",
                "gamma-app-docs": "1.4.2",
            }
        )
        client = _client(platform_root, fake_git, _Reader(None), writer)
        response = client.post("/api/onboard/app", json=_ONBOARD)
        assert response.status_code == 200, response.text
        assert len(writer.created) == 1
        created = writer.created[0]
        assert created["branch"] == "deploy-test"
        assert (
            created["repo_url"]
            == "https://github.com/Test-Org/gamma-app"
        )
        files = created["files"]
        assert set(files) == {
            "dev/Chart.yaml",
            "dev/values.yaml",
            "prod/Chart.yaml",
            "prod/values.yaml",
        }
        assert "version: 1.2.0" in files["prod/Chart.yaml"]
        assert "oci://ghcr.io/test-org/charts" in files["prod/Chart.yaml"]
        assert "tag: 1.4.2" in files["prod/values.yaml"]
        assert (
            "repository: ghcr.io/test-org/gamma-app-server"
            in files["prod/values.yaml"]
        )
        # The branch the studio stands up names THIS install's hostname, so it
        # cannot inherit the chart's authored-against-another-install default.
        assert yaml.safe_load(files["prod/values.yaml"])["gamma-app"]["host"] == (
            "gamma-app.lab.example.dev"
        )
        # The PR body records that the branch is already stood up.
        assert "was stood up by this onboarding" in fake_git.finalized[0]["pr_body"]

    def test_an_existing_branch_is_never_touched(
        self, platform_root: Path, fake_git: FakeGitPr
    ) -> None:
        writer = _Writer({"charts/gamma-app": "1.2.0", "gamma-app-server": "1.0.0"})
        reader = _Reader(frozenset({"prod/values.yaml"}))
        client = _client(platform_root, fake_git, reader, writer)
        assert client.post("/api/onboard/app", json=_ONBOARD).status_code == 200
        assert writer.created == []

    def test_unreadable_versions_leave_the_branch_to_the_runbook(
        self, platform_root: Path, fake_git: FakeGitPr
    ) -> None:
        # No chart published yet (CI has not run): nothing is created, the
        # onboarding itself proceeds, and the checklist keeps the runbook step.
        writer = _Writer({"gamma-app-server": "1.0.0"})
        client = _client(platform_root, fake_git, _Reader(None), writer)
        response = client.post("/api/onboard/app", json=_ONBOARD)
        assert response.status_code == 200
        assert writer.created == []
        assert "the team stands up" in fake_git.finalized[0]["pr_body"]


class TestRenderDeployBranch:
    def test_single_image_shape(self) -> None:
        files = dict(
            render_deploy_branch(
                app="solo",
                registry="ghcr.io/test-org",
                components=(),
                chart_version="2.0.0",
                image_tags={"solo": "2.3.4"},
                zone="test.example",
                environments=("dev", "prod"),
            )
        )
        values = yaml.safe_load(files["prod/values.yaml"])
        assert values == {
            "solo": {
                "host": "solo.test.example",
                "image": {"repository": "ghcr.io/test-org/solo", "tag": "2.3.4"},
            }
        }
        assert "version: 2.0.0" in files["dev/Chart.yaml"]

    def test_missing_tag_fails_closed(self) -> None:
        with pytest.raises(ValueError, match="no tag for 'duo-web'"):
            render_deploy_branch(
                app="duo",
                registry="ghcr.io/test-org",
                components=("api", "web"),
                chart_version="1.0.0",
                image_tags={"duo-api": "1.0.0"},
                zone="test.example",
                environments=("dev", "prod"),
            )

    def test_missing_zone_fails_closed(self) -> None:
        # Rendering without the install's zone would emit a branch that
        # inherits the chart's default hostname - the very thing the key
        # exists to prevent - so it refuses rather than rendering silently.
        with pytest.raises(ValueError, match="no install zone"):
            render_deploy_branch(
                app="solo",
                registry="ghcr.io/test-org",
                components=(),
                chart_version="1.0.0",
                image_tags={"solo": "1.0.0"},
                zone="",
                environments=("dev", "prod"),
            )

    def test_every_env_pins_this_installs_hostname(self) -> None:
        # Both envs, not just prod: dev inherits the chart default just as
        # silently (INT-FOUNDRY-020 keeps the two the same shape).
        files = dict(
            render_deploy_branch(
                app="duo",
                registry="ghcr.io/test-org",
                components=("api", "docs"),
                chart_version="1.0.0",
                image_tags={"duo-api": "1.0.0", "duo-docs": "1.0.0"},
                zone="example.org",
                environments=("dev", "prod"),
            )
        )
        for env in ("dev", "prod"):
            values = yaml.safe_load(files[f"{env}/values.yaml"])
            assert values["duo"]["host"] == "duo.example.org"

    def test_renders_exactly_the_declared_environments(self) -> None:
        # The folder set IS the declaration: a single-environment install
        # renders one folder, and no dormant sibling appears beside it.
        files = dict(
            render_deploy_branch(
                app="solo",
                registry="ghcr.io/test-org",
                components=(),
                chart_version="1.0.0",
                image_tags={"solo": "1.0.0"},
                zone="test.example",
                environments=("prod",),
            )
        )
        assert sorted(files) == ["prod/Chart.yaml", "prod/values.yaml"]
