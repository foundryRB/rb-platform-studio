"""HTTP integration tests: reads, gated onboarding, capability surfaces."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from pytest_intent import intent

from studio.adapters.inbound.http.app import create_app
from studio.container import Container
from studio.domain.services.team_documents import GRANT_FILES
from studio.domain.services.team_skeleton import SKELETON_FILE_ORDER, render_team_skeleton
from tests.conftest import FakeGitPr, StubConformance


class TestReads:
    def test_list_apps_joins_manifest_and_team_folders(self, client: TestClient) -> None:
        res = client.get("/api/apps")
        assert res.status_code == 200
        apps = {app["name"]: app for app in res.json()}
        assert set(apps) == {"alpha-app", "beta-app"}
        assert apps["alpha-app"]["role"] == "parts"
        assert apps["beta-app"]["role"] == "output"
        # The MCP URL derives from the entry's flag and the install zone.
        assert apps["alpha-app"]["mcp_url"] == "https://alpha-app.lab.example.dev/mcp"
        assert apps["alpha-app"]["manifest"]["hostname"] == "alpha-app.lab.example.dev"
        assert apps["alpha-app"]["manifest"]["has_database"] is False
        assert apps["beta-app"]["mcp_url"] is None
        assert apps["beta-app"]["manifest"]["has_database"] is True
        assert apps["alpha-app"]["manifest"]["has_identity"] is False
        assert apps["beta-app"]["manifest"]["has_identity"] is True

    def test_get_app_returns_team_folder_facts(self, client: TestClient) -> None:
        res = client.get("/api/apps/alpha-app")
        assert res.status_code == 200
        body = res.json()
        assert body["manifest"]["repo_url"] == "https://github.com/Test-Org/alpha-app"
        assert body["manifest"]["target_revision"] == "deploy-test"
        assert body["manifest"]["display_name"] == "Alpha App"

    def test_get_unknown_app_is_404(self, client: TestClient) -> None:
        res = client.get("/api/apps/no-such-app")
        assert res.status_code == 404
        assert res.json()["error"] == "EntityNotFoundError"

    def test_claims_come_from_the_platform_intent(self, client: TestClient) -> None:
        res = client.get("/api/claims")
        assert res.status_code == 200
        ids = {claim["claim_id"] for claim in res.json()}
        assert ids == {"INT-TEST-001", "INT-TEST-002"}

    def test_conformance_run_reports_per_check_rows(self, client: TestClient) -> None:
        res = client.post("/api/conformance/run")
        assert res.status_code == 200
        body = res.json()
        assert body["ok"] is True
        assert body["passed"] == 3
        assert any("[beta-app]" in row["node_id"] for row in body["results"])


class TestOnboardApp:
    @intent("INT-GATE-002")
    def test_onboarding_ships_as_a_pr_never_on_the_deploy_branch(
        self, client: TestClient, platform_root: Path, fake_git: FakeGitPr
    ) -> None:
        """INT-GATE-002: a gate-passing onboarding rides onboard/<app> into a PR."""
        res = client.post(
            "/api/onboard/app",
            json={
                "name": "gamma-app",
                "display_name": "Gamma App",
                "description": "The gamma application",
                "icon": "mdi-gamma",
                "expose_mcp": True,
            },
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["branch"] == "onboard/gamma-app"
        assert body["pr"]["number"] == 7
        assert fake_git.prepared == ["onboard/gamma-app"]
        assert fake_git.finalized[0]["commit_message"] == "feat(teams): onboard gamma-app"
        assert fake_git.aborted == []
        # No direct commit rode along: the deploy branch is only written by merge.
        assert fake_git.direct_commits == []

    @intent("INT-SKELETON-001")
    def test_team_folder_is_rendered_from_canonical_templates(
        self, client: TestClient, platform_root: Path
    ) -> None:
        """INT-SKELETON-001: the new folder is rendered from the studio's canonical
        skeleton templates keyed on the install's own facts (zone, tunnel, operators,
        deploy branch), not copied from a donor; grant files are not part of it."""
        client.post(
            "/api/onboard/app",
            json={
                "name": "gamma-app",
                "display_name": "Gamma App",
                "description": "The gamma application",
                "icon": "mdi-gamma",
                "expose_mcp": False,
            },
        )
        folder = platform_root / "teams" / "gamma-app"
        assert sorted(p.name for p in folder.iterdir()) == [
            "application.yaml",
            "gateway.yaml",
            "namespace.yaml",
            "rbac.yaml",
            "routes.yaml",
        ]
        gateway = (folder / "gateway.yaml").read_text(encoding="utf-8")
        assert "alpha-app" not in gateway
        assert "hostname: gamma-app.lab.example.dev" in gateway
        # The DNS target is the install's tunnel, rendered from values.yaml (not a
        # donor's baked target).
        assert "target: 00000000-0000-0000-0000-000000000000.cfargotunnel.com" in gateway
        routes = (folder / "routes.yaml").read_text(encoding="utf-8")
        # The route only routes: the tile facts live in the manifest entry (the
        # single source the platform chart renders the homepage tile from), so
        # no homepage annotation is rendered here.
        assert "gethomepage.dev" not in routes
        manifest = (platform_root / "foundry.yaml").read_text(encoding="utf-8")
        assert "display: Gamma App" in manifest
        assert 'description: "The gamma application"' in manifest
        assert "icon: mdi-gamma" in manifest
        # A letter-leading app's docs Service is the plain <app>-docs.
        assert "- name: gamma-app-docs" in routes
        rbac = (folder / "rbac.yaml").read_text(encoding="utf-8")
        # RBAC subjects are the install's operators, from values.yaml.
        assert 'name: "operator@example.test"' in rbac
        application = (folder / "application.yaml").read_text(encoding="utf-8")
        # The Application tracks THIS install's per-install deploy branch (deploy-test),
        # never a donor's `deploy`, and the app repo is the fleet org + app name.
        assert "targetRevision: deploy-test" in application
        assert "git-branch: deploy-test" in application
        assert (
            "repoURL: https://github.com/Test-Org/gamma-app"
            in application
        )

    @intent("INT-SKELETON-001")
    def test_every_render_input_reaches_the_rendered_folder(self) -> None:
        """INT-SKELETON-001: tokens and substitutions correspond exactly.

        An unfilled placeholder fails the render loudly. The opposite - a
        substitution for a placeholder the templates no longer carry - renders
        nothing and reports nothing, so it survives every suite that reads the
        output. Sentinels make each input's absence visible: an input that
        reaches no file is a fact the folder silently stopped carrying.
        """
        rendered = "".join(
            text
            for _, text in render_team_skeleton(
                app="sentinel-app",
                zone="zone.sentinel",
                tunnel_id="tunnel-sentinel",
                install="install-sentinel",
                operators=("operator-sentinel",),
                entry_env="env-sentinel",
                image_components=("component-sentinel",),
                repo="repo-sentinel",
            )
        )
        for sentinel in (
            "sentinel-app",
            "zone.sentinel",
            "tunnel-sentinel",
            "install-sentinel",
            "operator-sentinel",
            "env-sentinel",
            "component-sentinel",
            "repo-sentinel",
        ):
            assert sentinel in rendered, (
                f"{sentinel} reaches no rendered file: its placeholder has left the "
                "templates, so the substitution carrying it is dead"
            )

    @intent("INT-SKELETON-001")
    def test_an_explicit_repo_points_the_application_at_it_and_nothing_else(
        self, client: TestClient, platform_root: Path
    ) -> None:
        """INT-SKELETON-001: the repository is a fact separate from the app
        name. An app onboarded under a short name from a longer-named
        repository renders its Application at the repository, while the
        namespace, hostname, chart, and GHCR packages stay on the app name."""
        res = client.post(
            "/api/onboard/app",
            json={
                "name": "csd",
                "display_name": "CSD",
                "description": "Cognitive software delivery",
                "icon": "mdi-brain",
                "expose_mcp": False,
                "repo": "cognitive-software-delivery",
            },
        )
        assert res.status_code == 200, res.text
        folder = platform_root / "teams" / "csd"
        application = (folder / "application.yaml").read_text(encoding="utf-8")
        assert (
            "repoURL: https://github.com/Test-Org/"
            "cognitive-software-delivery" in application
        )
        # The fleet name drives everything the platform binds: the image the
        # Updater watches is the app's, not the repository's.
        assert "cognitive-software-delivery" not in application.split("repoURL:", 1)[1].split(
            "\n", 1
        )[1]
        assert "ghcr.io/test-org/csd" in application
        gateway = (folder / "gateway.yaml").read_text(encoding="utf-8")
        assert "hostname: csd.lab.example.dev" in gateway
        assert "cognitive-software-delivery" not in gateway

    @intent("INT-SKELETON-001")
    def test_a_repo_that_is_not_a_repo_name_is_rejected(self, client: TestClient) -> None:
        """INT-SKELETON-001: repo names a repository under the fleet org, not a
        URL or an owner/repo pair; anything else would render a broken pointer."""
        res = client.post(
            "/api/onboard/app",
            json={
                "name": "delta-app",
                "display_name": "Delta App",
                "description": "The delta application",
                "icon": "mdi-delta",
                "expose_mcp": False,
                "repo": "https://github.com/Test-Org/delta-app",
            },
        )
        assert res.status_code == 400, res.text

    @intent("INT-SKELETON-001")
    def test_digit_leading_app_docs_route_targets_the_letter_prefixed_service(
        self, client: TestClient, platform_root: Path
    ) -> None:
        """INT-SKELETON-001: a digit-leading app name (a legal DNS label) cannot
        name a Service (DNS-1035 wants a leading letter), so its chart ships the
        docs Service as svc-<app>-docs and the rendered route's backendRef targets
        that name. The HTTPRoute keeps the <app>-docs name (a DNS-1123 name, digit
        legal) the homepage tile selector derives from."""
        res = client.post(
            "/api/onboard/app",
            json={
                "name": "2beta-app",
                "display_name": "Beta App",
                "description": "The beta application",
                "icon": "mdi-beta",
                "expose_mcp": False,
            },
        )
        assert res.status_code == 200, res.text
        routes = (platform_root / "teams" / "2beta-app" / "routes.yaml").read_text(
            encoding="utf-8"
        )
        assert "name: 2beta-app-docs\n" in routes
        assert "- name: svc-2beta-app-docs" in routes
        assert "- name: 2beta-app-docs" not in routes

    @intent("INT-PROMOTE-001")
    def test_single_image_onboarding_binds_the_one_released_package(
        self, client: TestClient, platform_root: Path
    ) -> None:
        """INT-PROMOTE-001: with no component list the app releases one package,
        <app>, and the alias binds <app>.image.{repository,tag}."""
        client.post(
            "/api/onboard/app",
            json={
                "name": "gamma-app",
                "display_name": "Gamma App",
                "description": "The gamma application",
                "icon": "mdi-gamma",
                "expose_mcp": False,
            },
        )
        application = (platform_root / "teams" / "gamma-app" / "application.yaml").read_text(
            encoding="utf-8"
        )
        assert (
            "argocd-image-updater.argoproj.io/image-list: "
            "app=ghcr.io/test-org/gamma-app" in application
        )
        assert "app.helm.image-name: gamma-app.image.repository" in application
        assert "app.helm.image-tag: gamma-app.image.tag" in application

    @intent("INT-PROMOTE-001")
    def test_multi_image_onboarding_binds_one_alias_per_component(
        self, client: TestClient, platform_root: Path
    ) -> None:
        """INT-PROMOTE-001: the component list renders one Image Updater alias
        per released image - package <app>-<component>, values path
        <app>.images.<component>.{repository,tag} - and no single-image
        binding remains to watch a package the app does not release."""
        res = client.post(
            "/api/onboard/app",
            json={
                "name": "gamma-app",
                "display_name": "Gamma App",
                "description": "The gamma application",
                "icon": "mdi-gamma",
                "expose_mcp": False,
                "image_components": ["server", "client", "docs"],
            },
        )
        assert res.status_code == 200, res.text
        application = (platform_root / "teams" / "gamma-app" / "application.yaml").read_text(
            encoding="utf-8"
        )
        assert (
            "argocd-image-updater.argoproj.io/image-list: "
            "server=ghcr.io/test-org/gamma-app-server,"
            "client=ghcr.io/test-org/gamma-app-client,"
            "docs=ghcr.io/test-org/gamma-app-docs" in application
        )
        for component in ("server", "client", "docs"):
            assert f"{component}.update-strategy: semver" in application
            assert (
                f"{component}.helm.image-name: gamma-app.images.{component}.repository"
                in application
            )
            assert f"{component}.helm.image-tag: gamma-app.images.{component}.tag" in application
        # No single-image binding remains: that alias would watch the unreleased
        # package gamma-app and write a path the chart does not read.
        assert "app=ghcr.io/" not in application
        assert "gamma-app.image.tag" not in application

    @intent("INT-PROMOTE-001")
    def test_invalid_image_component_refuses_the_onboarding(
        self, client: TestClient, platform_root: Path
    ) -> None:
        """INT-PROMOTE-001: a component name that cannot become a package
        suffix and values key refuses the onboarding before anything lands."""
        res = client.post(
            "/api/onboard/app",
            json={
                "name": "gamma-app",
                "display_name": "Gamma App",
                "description": "The gamma application",
                "icon": "mdi-gamma",
                "expose_mcp": False,
                "image_components": ["Server!"],
            },
        )
        assert res.status_code == 400
        assert "image component" in res.json()["detail"]
        assert not (platform_root / "teams" / "gamma-app").exists()

    @intent("INT-PROMOTE-001")
    def test_lone_app_component_refuses_the_onboarding(
        self, client: TestClient, platform_root: Path
    ) -> None:
        """INT-PROMOTE-001: a lone 'app' component list is the single-image
        shape mis-declared - rendered multi (gamma-app-app) but read single by
        the shape check - so it is refused before anything lands."""
        res = client.post(
            "/api/onboard/app",
            json={
                "name": "gamma-app",
                "display_name": "Gamma App",
                "description": "The gamma application",
                "icon": "mdi-gamma",
                "expose_mcp": False,
                "image_components": ["app"],
            },
        )
        assert res.status_code == 400
        assert "single-image shape" in res.json()["detail"]
        assert not (platform_root / "teams" / "gamma-app").exists()

    @intent("INT-SKELETON-002")
    def test_homepage_group_is_derived_from_role(
        self, client: TestClient, platform_root: Path
    ) -> None:
        """INT-SKELETON-002: the app's homepage group has ONE source, its manifest
        role (parts -> Foundry, output -> Apps), consumed by the platform chart's
        manifest-rendered tiles. The rendered folder carries no competing group
        annotation at all, so the split-brain (tile under one heading, docs index
        under the other) has nothing to drift with."""
        client.post(
            "/api/onboard/app",
            json={
                "name": "gamma-app",
                "display_name": "Gamma App",
                "description": "The gamma application",
                "icon": "mdi-gamma",
                "expose_mcp": False,
            },
        )
        client.post(
            "/api/onboard/app",
            json={
                "name": "tool-app",
                "display_name": "Tool App",
                "description": "A Foundry part",
                "icon": "mdi-tools",
                "expose_mcp": False,
                "role": "parts",
            },
        )
        for app in ("gamma-app", "tool-app"):
            folder = platform_root / "teams" / app
            for path in folder.iterdir():
                assert "gethomepage.dev" not in path.read_text(encoding="utf-8"), (
                    f"{app}/{path.name} renders a homepage annotation; the manifest "
                    "role is the group's single source"
                )
        # The entries landed under their role blocks, where the chart reads them.
        manifest = (platform_root / "foundry.yaml").read_text(encoding="utf-8")
        parts_block = manifest.split("output:", 1)[0]
        output_block = manifest.split("output:", 1)[1]
        assert "- name: tool-app" in parts_block
        assert "- name: gamma-app" in output_block

    def test_manifest_gains_sorted_entry_with_mcp_flag(
        self, client: TestClient, platform_root: Path
    ) -> None:
        client.post(
            "/api/onboard/app",
            json={
                "name": "aaa-app",
                "display_name": "AAA",
                "description": "First alphabetically",
                "icon": "mdi-a",
                "expose_mcp": True,
            },
        )
        manifest = (platform_root / "foundry.yaml").read_text(encoding="utf-8")
        assert manifest.index("- name: aaa-app") < manifest.index("- name: beta-app")
        assert "  display: AAA\n" in manifest
        assert "  mcp: true" in manifest
        # The entry lands in output (the default role), not parts.
        assert manifest.index("output:") < manifest.index("- name: aaa-app")
        # The comments survive a manifest edit byte-for-byte.
        assert "# Test install manifest (ADR-032)." in manifest
        # Nothing stores the MCP URL; it derives from the zone at read time.
        assert "https://" not in manifest
        res = client.get("/api/apps/aaa-app")
        assert res.json()["mcp_url"] == "https://aaa-app.lab.example.dev/mcp"

    def test_parts_role_lands_in_the_parts_list(
        self, client: TestClient, platform_root: Path
    ) -> None:
        res = client.post(
            "/api/onboard/app",
            json={
                "name": "tool-app",
                "display_name": "Tool App",
                "description": "A Foundry part",
                "icon": "mdi-tools",
                "expose_mcp": False,
                "role": "parts",
            },
        )
        assert res.status_code == 200, res.text
        manifest = (platform_root / "foundry.yaml").read_text(encoding="utf-8")
        assert manifest.index("parts:") < manifest.index("- name: tool-app")
        assert manifest.index("- name: tool-app") < manifest.index("output:")
        assert client.get("/api/apps/tool-app").json()["role"] == "parts"

    def test_unknown_role_is_rejected(self, client: TestClient) -> None:
        res = client.post(
            "/api/onboard/app",
            json={
                "name": "gamma-app",
                "display_name": "Gamma App",
                "description": "The gamma application",
                "icon": "mdi-gamma",
                "expose_mcp": False,
                "role": "sideways",
            },
        )
        assert res.status_code == 422  # the schema pins role to parts|output

    @intent("INT-GEN-001")
    def test_onboarding_writes_only_authored_artifacts(
        self, client: TestClient, platform_root: Path
    ) -> None:
        """INT-GEN-001: the change is the manifest entry plus the team folder;
        no derived view (dashboards, homepage, docs index) exists as a file."""
        before = {p.relative_to(platform_root) for p in platform_root.rglob("*") if p.is_file()}
        res = client.post(
            "/api/onboard/app",
            json={
                "name": "gamma-app",
                "display_name": "Gamma App",
                "description": "The gamma application",
                "icon": "mdi-gamma",
                "expose_mcp": False,
            },
        )
        after = {p.relative_to(platform_root) for p in platform_root.rglob("*") if p.is_file()}
        created = {path.as_posix() for path in after - before}
        assert created == {
            "teams/gamma-app/application.yaml",
            "teams/gamma-app/gateway.yaml",
            "teams/gamma-app/namespace.yaml",
            "teams/gamma-app/rbac.yaml",
            "teams/gamma-app/routes.yaml",
        }
        changed = set(res.json()["changed_files"])
        assert changed == created | {"foundry.yaml"}

    def test_invalid_name_is_400(self, client: TestClient) -> None:
        res = client.post(
            "/api/onboard/app",
            json={
                "name": "Bad_Name",
                "display_name": "Bad",
                "description": "Bad",
                "icon": "mdi-bad",
                "expose_mcp": False,
            },
        )
        assert res.status_code == 400

    def test_existing_app_is_409(self, client: TestClient) -> None:
        res = client.post(
            "/api/onboard/app",
            json={
                "name": "alpha-app",
                "display_name": "Alpha",
                "description": "Already there",
                "icon": "mdi-alpha",
                "expose_mcp": False,
            },
        )
        assert res.status_code == 409


class TestOnboardDatabase:
    def test_database_grant_lands_in_the_concern_files(
        self, client: TestClient, platform_root: Path, fake_git: FakeGitPr
    ) -> None:
        res = client.post("/api/onboard/database", json={"name": "alpha-app"})
        assert res.status_code == 200, res.text
        folder = platform_root / "teams" / "alpha-app"
        jobs = (folder / "jobs.yaml").read_text(encoding="utf-8")
        assert "pg-alpha-app-provision" in jobs
        assert 'CREATE DATABASE "alpha-app" OWNER "alpha-app"' in jobs
        # The two isolation fixes the template guarantees (sabbito-bazarrito#7): a
        # per-app credential name, never the shared bare pg-app, and the PG16 SET-role
        # self-grant before CREATE DATABASE.
        assert "secretName: pg-app-alpha-app" in jobs
        assert 'GRANT "alpha-app" TO CURRENT_USER WITH SET TRUE' in jobs
        # The grant mints the credential the Job consumes: the generate-if-absent
        # block ships in the same change (ADR-034, INT-GRANT-003), split by concern.
        assert "name: gen-pg-app-alpha-app" in jobs
        assert "kubectl create secret generic pg-app-alpha-app" in jobs
        assert "reflection-auto-namespaces=databases" in jobs
        sa = (folder / "serviceaccount.yaml").read_text(encoding="utf-8")
        assert "kind: ServiceAccount" in sa and "gen-pg-app-alpha-app" in sa
        # The generator's RBAC lands in the grant's OWN file, never the skeleton's
        # rbac.yaml, so reconcile cannot re-render it away (INT-SKELETON-001).
        grant_rbac = (folder / "grant-rbac.yaml").read_text(encoding="utf-8")
        assert "kind: Role" in grant_rbac and "gen-pg-app-alpha-app" in grant_rbac
        assert "kind: RoleBinding" in grant_rbac
        # The skeleton's team RBAC is untouched by the grant.
        rbac = (folder / "rbac.yaml").read_text(encoding="utf-8")
        assert "gen-pg-app-alpha-app" not in rbac
        assert rbac.startswith("apiVersion: rbac.authorization.k8s.io/v1")
        assert "alpha-app-team-edit" in rbac
        assert "beta-app" not in jobs  # rendered from the studio template, not a neighbour
        assert fake_git.prepared == ["onboard/alpha-app-db"]
        assert (
            fake_git.finalized[0]["commit_message"]
            == "feat(databases): onboard alpha-app database"
        )

    def test_second_database_is_409(self, client: TestClient) -> None:
        res = client.post("/api/onboard/database", json={"name": "beta-app"})
        assert res.status_code == 409

    def test_unregistered_app_is_404(self, client: TestClient) -> None:
        res = client.post("/api/onboard/database", json={"name": "no-such-app"})
        assert res.status_code == 404


class TestReconcileLeavesGrantsAlone:
    """The invariant reconcile has always claimed, now checkable.

    Reconcile re-renders every skeleton file wholesale. Its promise that a
    grant survives it therefore rests entirely on no grant document living in
    a skeleton file -- which was false while the grants routed Role and
    RoleBinding into the skeleton's rbac.yaml by kind. Reconciling solveos
    deleted the gen-pg-app-solveos Role and RoleBinding, tenants pruned them,
    and the wave-2 generator Job ran as a ServiceAccount with no permissions
    and failed out its backoffLimit for hours before anyone read the alert
    (foundry-platform#100).
    """

    @intent("INT-SKELETON-001")
    def test_skeleton_and_grant_file_sets_are_disjoint(self) -> None:
        """INT-SKELETON-001: no file a grant writes is a file reconcile re-renders.

        The static half. A single shared filename is enough to reintroduce the
        whole failure, so it is asserted over the two named sets rather than
        left to whoever next adds a kind to the routing map."""
        assert GRANT_FILES.isdisjoint(SKELETON_FILE_ORDER)

    @intent("INT-SKELETON-001")
    def test_a_granted_database_survives_a_reconcile(
        self, client: TestClient, platform_root: Path
    ) -> None:
        """INT-SKELETON-001: reconciling an app leaves its database grant intact.

        The behavioural half, driven end to end through the two real use cases:
        grant, then reconcile, then read the folder. This is the sequence that
        broke solveos."""
        assert client.post("/api/onboard/database", json={"name": "alpha-app"}).status_code == 200
        folder = platform_root / "teams" / "alpha-app"
        before = (folder / "grant-rbac.yaml").read_text(encoding="utf-8")
        assert "gen-pg-app-alpha-app" in before

        res = client.post(
            "/api/reconcile/app",
            json={"name": "alpha-app", "image_components": ["api", "web"]},
        )
        assert res.status_code == 200, res.text

        # The whole grant is still there, byte for byte: the RBAC that lets the
        # generator run, its ServiceAccount, and both Jobs.
        assert (folder / "grant-rbac.yaml").read_text(encoding="utf-8") == before
        sa = (folder / "serviceaccount.yaml").read_text(encoding="utf-8")
        assert "gen-pg-app-alpha-app" in sa
        jobs = (folder / "jobs.yaml").read_text(encoding="utf-8")
        assert "gen-pg-app-alpha-app" in jobs and "pg-alpha-app-provision" in jobs
        # And the reconcile did what it is for: the fresh image declaration landed.
        application = (folder / "application.yaml").read_text(encoding="utf-8")
        assert "alpha-app-api" in application and "alpha-app-web" in application
        # No grant file is among the paths a reconcile reports touching.
        changed = set(res.json()["changed_files"])
        assert not {path for path in changed if path.rsplit("/", 1)[-1] in GRANT_FILES}


class TestOnboardIdentity:
    def test_realm_grant_lands_in_the_concern_files(
        self, client: TestClient, platform_root: Path, fake_git: FakeGitPr
    ) -> None:
        res = client.post("/api/onboard/identity", json={"name": "alpha-app"})
        assert res.status_code == 200, res.text
        folder = platform_root / "teams" / "alpha-app"
        config = (folder / "config.yaml").read_text(encoding="utf-8")
        assert "keycloak-realm-alpha-app" in config
        assert "realm: alpha-app" in config
        # A google provider reusing the shared credential, and no reference leakage.
        assert "providerId: google" in config
        jobs = (folder / "jobs.yaml").read_text(encoding="utf-8")
        assert "keycloak-alpha-app-provision" in jobs
        # The grant mints the credential the realm Job and oauth2-proxy consume
        # (ADR-034, INT-GRANT-003).
        assert "name: gen-keycloak-alpha-app" in jobs
        assert "kubectl create secret generic keycloak-alpha-app" in jobs
        assert "reflection-auto-namespaces=identity" in jobs
        sa = (folder / "serviceaccount.yaml").read_text(encoding="utf-8")
        assert "gen-keycloak-alpha-app" in sa
        for text in (config, jobs, sa):
            assert "beta-app" not in text
        assert fake_git.prepared == ["onboard/alpha-app-identity"]
        assert (
            fake_git.finalized[0]["commit_message"] == "feat(identity): onboard alpha-app realm"
        )

    def test_pr_body_carries_the_google_callback(
        self, client: TestClient, fake_git: FakeGitPr
    ) -> None:
        """The one manual step is surfaced in the PR body so it cannot be forgotten."""
        client.post("/api/onboard/identity", json={"name": "alpha-app"})
        pr_body = fake_git.finalized[0]["pr_body"]
        assert (
            "https://keycloak.lab.example.dev/realms/alpha-app/broker/google/endpoint" in pr_body
        )
        assert "redirect_uri_mismatch" in pr_body

    def test_second_identity_is_409(self, client: TestClient) -> None:
        res = client.post("/api/onboard/identity", json={"name": "beta-app"})
        assert res.status_code == 409

    def test_unregistered_app_is_404(self, client: TestClient) -> None:
        res = client.post("/api/onboard/identity", json={"name": "no-such-app"})
        assert res.status_code == 404


class TestCapabilitySurfaces:
    def test_pr_routes_exist_only_in_the_pr_composition(
        self, client: TestClient, local_client: TestClient
    ) -> None:
        assert client.get("/api/prs").status_code == 200
        assert local_client.get("/api/prs").status_code == 404
        assert local_client.post("/api/sync/refresh").status_code == 404

    def test_open_prs_surface_after_an_onboarding(
        self, client: TestClient, fake_git: FakeGitPr
    ) -> None:
        client.post(
            "/api/onboard/app",
            json={
                "name": "gamma-app",
                "display_name": "Gamma App",
                "description": "The gamma application",
                "icon": "mdi-gamma",
                "expose_mcp": False,
            },
        )
        res = client.get("/api/prs")
        assert [pr["branch"] for pr in res.json()] == ["onboard/gamma-app"]

    def test_local_onboarding_leaves_the_working_tree(
        self, local_client: TestClient, platform_root: Path
    ) -> None:
        res = local_client.post(
            "/api/onboard/app",
            json={
                "name": "gamma-app",
                "display_name": "Gamma App",
                "description": "The gamma application",
                "icon": "mdi-gamma",
                "expose_mcp": False,
            },
        )
        assert res.status_code == 200
        body = res.json()
        assert body["branch"] is None
        assert body["pr"] is None
        assert (platform_root / "teams" / "gamma-app" / "application.yaml").is_file()


class TestPauseResume:
    @intent("INT-LIFECYCLE-001")
    def test_pause_then_resume_toggles_status_and_direct_commits(
        self, client: TestClient, platform_root: Path, fake_git: FakeGitPr
    ) -> None:
        """INT-LIFECYCLE-001: a toggle writes only the override and direct-commits
        it to the deploy branch, no PR."""
        application = platform_root / "teams" / "alpha-app" / "application.yaml"
        original = application.read_text(encoding="utf-8")

        paused = client.post("/api/apps/alpha-app/pause")
        assert paused.status_code == 200, paused.text
        assert paused.json()["status"] == "paused"
        assert paused.json()["manifest"]["paused"] is True
        assert "paused: true" in application.read_text(encoding="utf-8")
        # A direct commit to the deploy branch: no branch, no pull request.
        assert fake_git.direct_commits == [
            {
                "paths": ("teams/alpha-app/application.yaml",),
                "commit_message": "chore(lifecycle): pause alpha-app",
            }
        ]
        assert fake_git.finalized == []
        assert fake_git.prepared == []

        resumed = client.post("/api/apps/alpha-app/resume")
        assert resumed.status_code == 200, resumed.text
        assert resumed.json()["status"] == "running"
        # Resume restores the file byte-for-byte.
        assert application.read_text(encoding="utf-8") == original
        assert [c["commit_message"] for c in fake_git.direct_commits] == [
            "chore(lifecycle): pause alpha-app",
            "chore(lifecycle): resume alpha-app",
        ]
        assert fake_git.finalized == []

    def test_status_defaults_to_running(self, client: TestClient) -> None:
        assert client.get("/api/apps/alpha-app").json()["status"] == "running"

    def test_pause_unknown_app_is_404(self, client: TestClient) -> None:
        assert client.post("/api/apps/no-such-app/pause").status_code == 404

    def test_pause_is_idempotent(self, client: TestClient, fake_git: FakeGitPr) -> None:
        client.post("/api/apps/alpha-app/pause")
        again = client.post("/api/apps/alpha-app/pause")
        assert again.status_code == 200
        assert again.json()["status"] == "paused"
        assert len(fake_git.direct_commits) == 1  # already paused: no second commit

    def test_studio_refuses_to_pause_itself(self, platform_root: Path) -> None:
        container = Container(
            platform_root=platform_root,
            conformance=StubConformance(),
            git_pr=FakeGitPr(),
            self_app="alpha-app",
        )
        studio_client = TestClient(create_app(container))
        res = studio_client.post("/api/apps/alpha-app/pause")
        assert res.status_code == 409
        assert res.json()["error"] == "SelfPauseError"

    def test_local_pause_leaves_the_working_tree(
        self, local_client: TestClient, platform_root: Path
    ) -> None:
        res = local_client.post("/api/apps/alpha-app/pause")
        assert res.status_code == 200
        assert res.json()["status"] == "paused"
        assert "paused: true" in (
            platform_root / "teams" / "alpha-app" / "application.yaml"
        ).read_text(encoding="utf-8")


_FREEZE_LINE = 'argocd-image-updater.argoproj.io/app.ignore-tags: "*"'


class TestFreezePromotion:
    @intent("INT-LIFECYCLE-002")
    def test_freeze_then_resume_toggles_promotion_and_direct_commits(
        self, client: TestClient, platform_root: Path, fake_git: FakeGitPr
    ) -> None:
        """INT-LIFECYCLE-002: a toggle writes only the alias tag filters and
        direct-commits them to the deploy branch, no PR; resume restores the
        file byte-for-byte."""
        application = platform_root / "teams" / "alpha-app" / "application.yaml"
        original = application.read_text(encoding="utf-8")

        frozen = client.post("/api/apps/alpha-app/promotion/freeze")
        assert frozen.status_code == 200, frozen.text
        assert frozen.json()["promotion"] == "manual"
        assert frozen.json()["manifest"]["promotion"] == "manual"
        # Frozen is not paused: the app keeps running, it just stops taking versions.
        assert frozen.json()["status"] == "running"
        text = application.read_text(encoding="utf-8")
        assert _FREEZE_LINE in text
        # The binding itself survives, which is what keeps the promotion
        # conformance rows and the status read alive while the app is held.
        assert "argocd-image-updater.argoproj.io/image-list:" in text
        assert "argocd-image-updater.argoproj.io/app.helm.image-tag:" in text
        # A direct commit to the deploy branch: no branch, no pull request.
        assert fake_git.direct_commits == [
            {
                "paths": ("teams/alpha-app/application.yaml",),
                "commit_message": "chore(lifecycle): freeze promotion for alpha-app",
            }
        ]
        assert fake_git.finalized == []
        assert fake_git.prepared == []

        resumed = client.post("/api/apps/alpha-app/promotion/resume")
        assert resumed.status_code == 200, resumed.text
        assert resumed.json()["promotion"] == "auto"
        assert application.read_text(encoding="utf-8") == original
        assert [c["commit_message"] for c in fake_git.direct_commits] == [
            "chore(lifecycle): freeze promotion for alpha-app",
            "chore(lifecycle): resume promotion for alpha-app",
        ]
        assert fake_git.finalized == []

    def test_promotion_defaults_to_auto(self, client: TestClient) -> None:
        assert client.get("/api/apps/alpha-app").json()["promotion"] == "auto"

    def test_freeze_is_idempotent(self, client: TestClient, fake_git: FakeGitPr) -> None:
        client.post("/api/apps/alpha-app/promotion/freeze")
        again = client.post("/api/apps/alpha-app/promotion/freeze")
        assert again.status_code == 200
        assert again.json()["promotion"] == "manual"
        assert len(fake_git.direct_commits) == 1  # already frozen: no second commit

    def test_resume_of_a_promoting_app_is_a_no_op(
        self, client: TestClient, fake_git: FakeGitPr
    ) -> None:
        res = client.post("/api/apps/alpha-app/promotion/resume")
        assert res.status_code == 200
        assert res.json()["promotion"] == "auto"
        assert fake_git.direct_commits == []

    def test_freeze_unknown_app_is_404(self, client: TestClient) -> None:
        assert client.post("/api/apps/no-such-app/promotion/freeze").status_code == 404

    def test_freeze_without_bindings_is_refused(
        self, client: TestClient, platform_root: Path
    ) -> None:
        """An Application declaring no image-list already promotes nothing;
        saying so beats succeeding on a toggle that changed nothing."""
        application = platform_root / "teams" / "beta-app" / "application.yaml"
        application.write_text(
            "\n".join(
                line
                for line in application.read_text(encoding="utf-8").split("\n")
                if "argocd-image-updater.argoproj.io/" not in line
            ),
            encoding="utf-8",
        )
        res = client.post("/api/apps/beta-app/promotion/freeze")
        assert res.status_code == 409
        assert res.json()["error"] == "PromotionUnboundError"
        assert client.get("/api/apps/beta-app").json()["promotion"] == "none"

    def test_freeze_over_an_operator_tag_filter_is_refused(
        self, client: TestClient, platform_root: Path
    ) -> None:
        """An ignore-tags an operator wrote is a real filter, not the freeze
        sentinel; overwriting it would silently change what that alias promotes."""
        application = platform_root / "teams" / "alpha-app" / "application.yaml"
        original = application.read_text(encoding="utf-8")
        application.write_text(
            original.replace(
                "argocd-image-updater.argoproj.io/app.update-strategy: semver",
                "argocd-image-updater.argoproj.io/app.update-strategy: semver\n"
                "    argocd-image-updater.argoproj.io/app.ignore-tags: nightly-*",
            ),
            encoding="utf-8",
        )
        res = client.post("/api/apps/alpha-app/promotion/freeze")
        assert res.status_code == 409
        assert res.json()["error"] == "PromotionConflictError"
        # The refusal changed nothing.
        assert "nightly-*" in application.read_text(encoding="utf-8")
        assert _FREEZE_LINE not in application.read_text(encoding="utf-8")

    def test_the_studio_may_freeze_itself(self, platform_root: Path) -> None:
        """Unlike pause, freezing the studio's own app is allowed: it holds the
        control plane on its current version rather than scaling it away, so it
        stays running and able to unfreeze itself."""
        container = Container(
            platform_root=platform_root,
            conformance=StubConformance(),
            git_pr=FakeGitPr(),
            self_app="alpha-app",
        )
        studio_client = TestClient(create_app(container))
        res = studio_client.post("/api/apps/alpha-app/promotion/freeze")
        assert res.status_code == 200
        assert res.json()["promotion"] == "manual"

    def test_pause_and_freeze_are_independent(
        self, client: TestClient, platform_root: Path
    ) -> None:
        """The two toggles read and write different things, so an app can be
        paused and still promoting, or running and frozen."""
        paused = client.post("/api/apps/alpha-app/pause").json()
        assert (paused["status"], paused["promotion"]) == ("paused", "auto")
        frozen = client.post("/api/apps/alpha-app/promotion/freeze").json()
        assert (frozen["status"], frozen["promotion"]) == ("paused", "manual")
        resumed = client.post("/api/apps/alpha-app/resume").json()
        assert (resumed["status"], resumed["promotion"]) == ("running", "manual")
