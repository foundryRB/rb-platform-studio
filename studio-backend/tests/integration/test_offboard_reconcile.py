"""Offboard and reconcile: the day-2 verbs, exercised through the HTTP door.

Offboard is the inverse of onboarding (the whole record leaves in one gated
change, the namespace's volumes named as erased, stateful grants enumerated
for a disposition decision);
reconcile is the repair verb (the five skeleton files re-rendered from the
current templates and a fresh declaration, grant files untouched). Both ship
as pull requests on the same gate-validate-rollback path as onboarding.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pytest_intent import intent

from studio.adapters.inbound.http.app import create_app
from studio.container import Container
from tests.conftest import FakeGitPr, FakeProbe, StubConformance, failing_report, passing_report


class TestOffboard:
    def test_offboard_removes_the_whole_record_and_ships_the_pr(
        self, client: TestClient, platform_root: Path, fake_git: FakeGitPr
    ) -> None:
        response = client.post("/api/offboard/app", json={"name": "beta-app"})
        assert response.status_code == 200, response.text
        manifest = (platform_root / "foundry.yaml").read_text(encoding="utf-8")
        assert "beta-app" not in manifest
        assert not (platform_root / "teams" / "beta-app").exists()
        # The neighbour app is untouched.
        assert (platform_root / "teams" / "alpha-app" / "application.yaml").is_file()
        assert fake_git.finalized[0]["branch"] == "offboard/beta-app"
        assert fake_git.finalized[0]["commit_message"] == "feat(teams): offboard beta-app"

    def test_offboard_enumerates_stateful_grants_for_disposition(
        self, client: TestClient, fake_git: FakeGitPr
    ) -> None:
        # beta-app carries a database grant and an identity realm in the
        # fixture; the PR body must enumerate both and destroy neither.
        response = client.post("/api/offboard/app", json={"name": "beta-app"})
        assert response.status_code == 200
        body = fake_git.finalized[0]["pr_body"]
        assert "Data disposition" in body
        assert "shared PostgreSQL" in body
        assert "shared Keycloak" in body
        assert "pg-app-beta-app" in body
        assert "keycloak-beta-app" in body
        assert "Stateful teardown (above)" in body
        # A grant for a reused name provisions onto the retained datastore and
        # realm, so the name is free only once each grant is dropped.
        assert "`beta-app` is free for reuse once each grant above is dropped" in body

    def test_offboard_without_grants_carries_no_disposition_section(
        self, client: TestClient, fake_git: FakeGitPr
    ) -> None:
        response = client.post("/api/offboard/app", json={"name": "alpha-app"})
        assert response.status_code == 200
        body = fake_git.finalized[0]["pr_body"]
        assert "Data disposition" not in body
        assert "Stateful teardown" not in body
        assert "this frees the name `alpha-app` for reuse" in body

    @pytest.mark.parametrize("app", ["alpha-app", "beta-app"])
    def test_offboard_names_the_namespace_volumes_as_deleted(
        self, client: TestClient, fake_git: FakeGitPr, app: str
    ) -> None:
        # The prune deletes the namespace and every claim in it whether or not
        # the app holds a grant (beta-app does, alpha-app does not), and the PR
        # merges as it opens, so every body states the deletion and asks for
        # the copy to have come first.
        response = client.post("/api/offboard/app", json={"name": app})
        assert response.status_code == 200
        body = fake_git.finalized[0]["pr_body"]
        assert "deletes every volume the app's chart claims" in body
        assert "copied out before this PR opened" in body

    def test_offboarding_an_unknown_app_is_404(self, client: TestClient) -> None:
        assert client.post("/api/offboard/app", json={"name": "ghost-app"}).status_code == 404

    def test_offboarding_the_studio_itself_is_refused(
        self, platform_root: Path, fake_git: FakeGitPr
    ) -> None:
        container = Container(
            platform_root=platform_root,
            conformance=StubConformance(),
            git_pr=fake_git,
            self_app="beta-app",
            http_probe=FakeProbe(),
        )
        client = TestClient(create_app(container))
        response = client.post("/api/offboard/app", json={"name": "beta-app"})
        assert response.status_code == 409
        assert "studio itself" in response.text
        assert (platform_root / "teams" / "beta-app").is_dir()

    def test_failed_gate_restores_the_record_byte_identical(
        self, platform_root: Path, fake_git: FakeGitPr
    ) -> None:
        before = {
            path.name: path.read_text(encoding="utf-8")
            for path in (platform_root / "teams" / "beta-app").iterdir()
        }
        manifest_before = (platform_root / "foundry.yaml").read_text(encoding="utf-8")
        conformance = StubConformance([passing_report(), failing_report()])
        container = Container(
            platform_root=platform_root,
            conformance=conformance,
            git_pr=fake_git,
            http_probe=FakeProbe(),
        )
        client = TestClient(create_app(container))
        response = client.post("/api/offboard/app", json={"name": "beta-app"})
        assert response.status_code == 422
        assert (platform_root / "foundry.yaml").read_text(encoding="utf-8") == manifest_before
        after = {
            path.name: path.read_text(encoding="utf-8")
            for path in (platform_root / "teams" / "beta-app").iterdir()
        }
        assert after == before
        assert fake_git.aborted == ["offboard/beta-app"]
        assert fake_git.finalized == []


class TestReconcile:
    def test_reconcile_rerenders_the_skeleton_and_keeps_grant_files(
        self, client: TestClient, platform_root: Path, fake_git: FakeGitPr
    ) -> None:
        response = client.post(
            "/api/reconcile/app",
            json={
                "name": "beta-app",
                "image_components": ["server", "docs"],
                "description": "The beta application",
            },
        )
        assert response.status_code == 200, response.text
        application = (
            platform_root / "teams" / "beta-app" / "application.yaml"
        ).read_text(encoding="utf-8")
        assert "server=ghcr.io/test-org/beta-app-server" in application
        assert "docs=ghcr.io/test-org/beta-app-docs" in application
        assert "beta-app.images.server.tag" in application
        # A promoting, running app stays so: nothing frozen, nothing paused.
        assert "ignore-tags" not in application
        assert "paused" not in application
        # Grant files survive every reconcile: a grant is a separate
        # onboarding's output.
        assert (platform_root / "teams" / "beta-app" / "jobs.yaml").is_file()
        assert (platform_root / "teams" / "beta-app" / "config.yaml").is_file()
        assert fake_git.finalized[0]["branch"] == "reconcile/beta-app"
        assert fake_git.finalized[0]["commit_message"] == "fix(teams): reconcile beta-app"

    @intent("INT-LIFECYCLE-004")
    def test_reconcile_keeps_a_frozen_app_frozen(
        self, client: TestClient, platform_root: Path, fake_git: FakeGitPr
    ) -> None:
        """INT-LIFECYCLE-004: the re-rendered Application carries the freeze on
        every alias the fresh declaration names, the new ones included."""
        frozen = client.post("/api/apps/beta-app/promotion/freeze")
        assert frozen.json()["promotion"] == "manual"
        response = client.post(
            "/api/reconcile/app",
            json={"name": "beta-app", "image_components": ["server", "docs"]},
        )
        assert response.status_code == 200, response.text
        application = (
            platform_root / "teams" / "beta-app" / "application.yaml"
        ).read_text(encoding="utf-8")
        for alias in ("server", "docs"):
            assert f'argocd-image-updater.argoproj.io/{alias}.ignore-tags: "*"' in application
        assert client.get("/api/apps/beta-app").json()["promotion"] == "manual"
        assert "kept frozen" in fake_git.finalized[0]["pr_body"]

    @intent("INT-LIFECYCLE-004")
    def test_reconcile_keeps_a_paused_app_paused(
        self, client: TestClient, platform_root: Path
    ) -> None:
        """INT-LIFECYCLE-004: a paused app comes out of a reconcile paused."""
        assert client.post("/api/apps/beta-app/pause").json()["status"] == "paused"
        response = client.post("/api/reconcile/app", json={"name": "beta-app"})
        assert response.status_code == 200, response.text
        app = client.get("/api/apps/beta-app").json()
        assert (app["status"], app["promotion"]) == ("paused", "auto")

    def test_reconcile_writes_the_description_into_the_manifest(
        self, client: TestClient, platform_root: Path
    ) -> None:
        response = client.post(
            "/api/reconcile/app",
            json={"name": "beta-app", "description": "The beta application"},
        )
        assert response.status_code == 200
        manifest = (platform_root / "foundry.yaml").read_text(encoding="utf-8")
        assert 'description: "The beta application"' in manifest
        # The entry keeps its role block, display, and icon.
        assert "display: Beta App" in manifest
        assert "icon: mdi-beta" in manifest

    @pytest.mark.parametrize(
        "payload",
        [{"name": "beta-app"}, {"name": "beta-app", "repo": "fleet-beta-app"}],
    )
    def test_reconcile_keeps_the_entry_repository(
        self, client: TestClient, platform_root: Path, payload: dict
    ) -> None:
        _ship_beta_from(platform_root, "fleet-beta-app")
        assert client.post("/api/reconcile/app", json=payload).status_code == 200
        assert "repo: fleet-beta-app" in _beta_entry(platform_root)
        application = (
            platform_root / "teams" / "beta-app" / "application.yaml"
        ).read_text(encoding="utf-8")
        assert "repoURL: https://github.com/Test-Org/fleet-beta-app" in application

    def test_reconcile_reads_the_repository_from_the_entry_first(
        self, client: TestClient, platform_root: Path
    ) -> None:
        # The manifest is the single source: a folder still pointing at the
        # app's own name is repaired to the entry's repository, not the reverse.
        _ship_beta_from(platform_root, "fleet-beta-app", folder=False)
        assert client.post("/api/reconcile/app", json={"name": "beta-app"}).status_code == 200
        assert "repo: fleet-beta-app" in _beta_entry(platform_root)
        application = (
            platform_root / "teams" / "beta-app" / "application.yaml"
        ).read_text(encoding="utf-8")
        assert "repoURL: https://github.com/Test-Org/fleet-beta-app" in application

    def test_reconcile_records_the_application_repository_on_a_bare_entry(
        self, client: TestClient, platform_root: Path
    ) -> None:
        # An entry that lost its `repo:` line is repaired from the Application.
        _ship_beta_from(platform_root, "fleet-beta-app", entry=False)
        assert client.post("/api/reconcile/app", json={"name": "beta-app"}).status_code == 200
        assert "repo: fleet-beta-app" in _beta_entry(platform_root)

    def test_reconcile_adds_no_repo_to_an_app_shipping_from_its_name(
        self, client: TestClient, platform_root: Path
    ) -> None:
        assert client.post("/api/reconcile/app", json={"name": "beta-app"}).status_code == 200
        assert "repo:" not in _beta_entry(platform_root)

    def test_reconcile_of_an_unknown_app_is_404(self, client: TestClient) -> None:
        assert client.post("/api/reconcile/app", json={"name": "ghost-app"}).status_code == 404

    def test_reconcile_refuses_a_bad_component_list(self, client: TestClient) -> None:
        response = client.post(
            "/api/reconcile/app",
            json={"name": "beta-app", "image_components": ["app"]},
        )
        assert response.status_code == 400

    @pytest.mark.parametrize("payload", [{"name": ""}, {}])
    def test_reconcile_validates_the_name(self, client: TestClient, payload: dict) -> None:
        assert client.post("/api/reconcile/app", json=payload).status_code == 422


def _ship_beta_from(
    root: Path, repo: str, *, entry: bool = True, folder: bool = True
) -> None:
    """Declare beta-app as shipping from ``repo``: in the manifest entry's
    `repo:` line, and in the Application pointer onboarding rendered."""
    if entry:
        manifest = root / "foundry.yaml"
        manifest.write_text(
            manifest.read_text(encoding="utf-8").replace(
                "- name: beta-app\n", f"- name: beta-app\n  repo: {repo}\n"
            ),
            encoding="utf-8",
        )
        assert f"repo: {repo}" in _beta_entry(root)
    if folder:
        application = root / "teams" / "beta-app" / "application.yaml"
        application.write_text(
            application.read_text(encoding="utf-8").replace(
                "Test-Org/beta-app\n", f"Test-Org/{repo}\n"
            ),
            encoding="utf-8",
        )
        assert f"Test-Org/{repo}" in application.read_text(encoding="utf-8")


def _beta_entry(root: Path) -> str:
    text = (root / "foundry.yaml").read_text(encoding="utf-8")
    return text.split("- name: beta-app")[1].split("- name:")[0]
