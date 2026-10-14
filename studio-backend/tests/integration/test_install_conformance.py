"""InstallConformanceRunner tests: the gate's checks over the working tree.

The runner exists because the platform's own suite reads committed deploy-*
branch refs and cannot see a candidate onboarding that lives only in the
working tree; these tests pin that the adapted checks judge exactly the
working-tree state the pull request would ship.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pytest_intent import intent

from studio.adapters.outbound.conformance_fs.install_conformance_runner import (
    InstallConformanceRunner,
)
from studio.domain.model.test_outcome import TestOutcome
from studio.domain.services.app_repo_scaffold import (
    SCAFFOLD_COMPONENTS,
    render_app_repo_scaffold,
)
from studio.domain.services.deploy_branch import render_deploy_branch
from studio.domain.services.environments import declared_environments, entry_environment
from studio.domain.services.team_documents import freeze_application_promotion
from studio.domain.services.team_skeleton import APP_REPO_ORG, render_team_skeleton


def _outcomes(root: Path) -> dict[str, TestOutcome]:
    report = InstallConformanceRunner(root).run()
    return {result.node_id: result.outcome for result in report.results}


class _StaticRepo:
    """AppRepoSource stub: canned answers for every app. Everything defaults
    to None (unreadable), so a row whose leg a test does not arm reports
    skipped. ``compose`` and ``docs_dockerfile`` are keyed by app (the repo
    URL basename), since the released set is genuinely per repo.
    ``repo_exists`` defaults to None, the answer that proves nothing: a test
    arms False only to assert the definite not-visible verdict.
    ``default_paths`` is the default branch's listing and ``deploy_paths``
    every other branch's; an empty file read is judged absent only when the
    default branch's listing answers without the file, so a test asserting a
    missing file arms ``default_paths``."""

    def __init__(
        self,
        values: dict | None = None,
        *,
        default_branch: str | None = None,
        build_workflow: str | None = None,
        deploy_paths: frozenset[str] | None = None,
        default_paths: frozenset[str] | None = None,
        compose: dict[str, str] | None = None,
        docs_dockerfile: dict[str, str] | None = None,
        chart_values: dict[str, str] | None = None,
        repo_exists: bool | None = None,
    ) -> None:
        self._values = values
        self._default_branch = default_branch
        self._repo_exists = repo_exists
        self._build_workflow = build_workflow
        self._deploy_paths = deploy_paths
        self._default_paths = default_paths
        self._compose = compose or {}
        self._docs_dockerfile = docs_dockerfile or {}
        self._chart_values = chart_values or {}
        self.calls: list[tuple[str, str, str]] = []

    def deploy_values(self, *, repo_url: str, branch: str, path: str) -> dict | None:
        self.calls.append((repo_url, branch, path))
        return self._values

    def repo_exists(self, *, repo_url: str) -> bool | None:
        return self._repo_exists

    def default_branch(self, *, repo_url: str) -> str | None:
        return self._default_branch

    def file_text(self, *, repo_url: str, branch: str, path: str) -> str | None:
        app = repo_url.rsplit("/", 1)[-1]
        if path == "devops/docker-compose.yml":
            return self._compose.get(app)
        if path == "docs/Dockerfile":
            return self._docs_dockerfile.get(app)
        if path == "k8s/values.yaml":
            return self._chart_values.get(app)
        return self._build_workflow

    def branch_paths(self, *, repo_url: str, branch: str) -> frozenset[str] | None:
        if branch == self._default_branch:
            return self._default_paths
        return self._deploy_paths


@pytest.mark.parametrize(
    ("chart", "override", "demand", "parity"),
    [
        (None, {}, TestOutcome.SKIPPED, TestOutcome.SKIPPED),
        ("host: ''\nauth:\n  existingSecret: keycloak-alpha-app\n", None,
         TestOutcome.SKIPPED, TestOutcome.SKIPPED),
        ("host: ''\nauth:\n  existingSecret: keycloak-alpha-app\n", {},
         TestOutcome.FAILED, TestOutcome.FAILED),
        ("host: ''\nauth:\n  enabled: false\n  existingSecret: keycloak-alpha-app\n",
         {"alpha-app": {"host": "alpha-app.lab.example.dev", "auth": {"enabled": True}}},
         TestOutcome.FAILED, TestOutcome.PASSED),
        ("host: ''\nauth:\n  existingSecret: keycloak-alpha-app\n",
         {"alpha-app": {"host": "alpha-app.lab.example.dev", "auth": {"enabled": False}}},
         TestOutcome.PASSED, TestOutcome.PASSED),
    ],
)
def test_effective_value_rows_require_answered_reads(
    platform_root: Path, chart: str | None, override: dict | None,
    demand: TestOutcome, parity: TestOutcome,
) -> None:
    source = _StaticRepo(
        values=override, default_branch="main",
        chart_values={"alpha-app": chart} if chart is not None else {},
    )
    rows = {r.node_id: r for r in InstallConformanceRunner(platform_root, source).run().results}
    for prefix, expected in (
        ("install/credentials::demand-grant", demand),
        ("install/parity::per-install-hostnames", parity),
    ):
        row = rows[f"{prefix}[alpha-app]"]
        assert row.outcome is expected
        if expected is TestOutcome.SKIPPED:
            assert ("chart values" if chart is None else "deploy values") in row.detail


# The env config INT-FOUNDRY-020 requires of a deploy branch, and a build.yml
# calling the shared reusable workflow of the conftest fixture's app-repo org
# (INT-FOUNDRY-013; the fixture Applications live under Test-Org).
_ENV_CONFIG = frozenset(
    {"dev/values.yaml", "dev/Chart.yaml", "prod/values.yaml", "prod/Chart.yaml"}
)
_CI_CALLER = "jobs:\n  build:\n    uses: Test-Org/ci/.github/workflows/build.yml@main\n"


def test_a_deploy_branch_folder_outside_the_declaration_fails(platform_root: Path) -> None:
    """INT-FOUNDRY-020, the reverse leg: the branch carries EXACTLY the declared
    environments. A folder the manifest does not declare is an environment nothing
    reconciles and nothing may promote into, so the row fails rather than leaving it
    sitting there dormant, which is what the fleet's stale dev/ folders were."""
    manifest = platform_root / "foundry.yaml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8") + "environments:\n- prod\n", encoding="utf-8"
    )
    source = _StaticRepo(
        {"alpha-app": {"image": {"tag": "1.2.3"}}, "beta-app": {"image": {"tag": "1.2.3"}}},
        default_branch="main",
        build_workflow=_CI_CALLER,
        # dev/ is no longer declared, and the branch still carries it.
        deploy_paths=_ENV_CONFIG,
    )
    results = {
        result.node_id: result
        for result in InstallConformanceRunner(platform_root, source).run().results
    }
    row = results["install/delivery::deploy-branch[alpha-app]"]
    assert row.outcome is TestOutcome.FAILED
    assert "outside the declaration" in (row.detail or "")
    assert "dev" in (row.detail or "")


def test_a_declared_environment_missing_from_the_branch_fails(platform_root: Path) -> None:
    """The forward leg: a declared environment with no folder on the branch gives
    the reconciler nothing to deliver there."""
    manifest = platform_root / "foundry.yaml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8") + "environments:\n- prod\n- staging\n",
        encoding="utf-8",
    )
    source = _StaticRepo(
        {"alpha-app": {"image": {"tag": "1.2.3"}}, "beta-app": {"image": {"tag": "1.2.3"}}},
        default_branch="main",
        build_workflow=_CI_CALLER,
        deploy_paths=frozenset({"prod/values.yaml", "prod/Chart.yaml"}),
    )
    results = {
        result.node_id: result
        for result in InstallConformanceRunner(platform_root, source).run().results
    }
    row = results["install/delivery::deploy-branch[alpha-app]"]
    assert row.outcome is TestOutcome.FAILED
    assert "staging" in (row.detail or "")


def test_conformant_checkout_passes_every_check(platform_root: Path) -> None:
    report = InstallConformanceRunner(platform_root).run()
    assert report.exit_code == 0
    outcomes = {result.node_id: result.outcome for result in report.results}
    assert outcomes["install/values::zone-declared"] is TestOutcome.PASSED
    assert outcomes["install/parity::manifest-teams-bijection"] is TestOutcome.PASSED
    assert outcomes["install/manifest::entry-shape[alpha-app]"] is TestOutcome.PASSED
    assert outcomes["install/mcp::derived-endpoint[alpha-app]"] is TestOutcome.PASSED
    assert outcomes["install/delivery::argocd-application[beta-app]"] is TestOutcome.PASSED
    assert outcomes["install/database::isolation-clean[beta-app]"] is TestOutcome.PASSED
    # The homepage group each route advertises matches its role: alpha (parts) is
    # Foundry, beta (output) is Apps.
    assert outcomes["install/homepage::group-matches-role[alpha-app]"] is TestOutcome.PASSED
    assert outcomes["install/homepage::group-matches-role[beta-app]"] is TestOutcome.PASSED
    # Only the flagged entry earns an MCP row.
    assert "install/mcp::derived-endpoint[beta-app]" not in outcomes
    # The Image Updater bindings are coherent (an install-owned fact). The
    # cross-repo agreement rows (promotes, released-set) are act-only: the
    # standing venue never emits them, so an app-side change cannot fail the
    # install report; the act venue (below) emits them skipped without a
    # wired source, and a skip never reads as red.
    assert outcomes["install/promotion::image-updater-coherent[alpha-app]"] is TestOutcome.PASSED
    assert "install/promotion::image-updater-promotes[alpha-app]" not in outcomes
    assert "install/promotion::image-updater-released-set[alpha-app]" not in outcomes
    act = {
        result.node_id: result.outcome
        for result in InstallConformanceRunner(platform_root, act_rows=True).run().results
    }
    assert act["install/promotion::image-updater-promotes[alpha-app]"] is TestOutcome.SKIPPED
    assert (
        act["install/promotion::image-updater-released-set[alpha-app]"]
        is TestOutcome.SKIPPED
    )
    assert act["install/onboarding::docs-image[alpha-app]"] is TestOutcome.SKIPPED
    # Likewise the team-side delivery rows: no wired source means no repo-host
    # read, so both legs report skipped rather than guessed.
    assert outcomes["install/delivery::ci-caller[alpha-app]"] is TestOutcome.SKIPPED
    assert outcomes["install/delivery::deploy-branch[alpha-app]"] is TestOutcome.SKIPPED


def test_homepage_group_mismatched_to_role_fails(platform_root: Path) -> None:
    # beta-app is output, so its route must be group Apps; flip it to Foundry and
    # the per-app row fails while its neighbour stays green.
    routes = platform_root / "teams" / "beta-app" / "routes.yaml"
    routes.write_text(
        routes.read_text(encoding="utf-8").replace(
            "gethomepage.dev/group: Apps", "gethomepage.dev/group: Foundry"
        ),
        encoding="utf-8",
    )
    outcomes = _outcomes(platform_root)
    assert outcomes["install/homepage::group-matches-role[beta-app]"] is TestOutcome.FAILED
    assert outcomes["install/homepage::group-matches-role[alpha-app]"] is TestOutcome.PASSED


def test_manifest_entry_without_a_folder_fails_the_bijection(platform_root: Path) -> None:
    manifest = platform_root / "foundry.yaml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8")
        + "- name: ghost-app\n  display: Ghost\n  icon: mdi-ghost\n",
        encoding="utf-8",
    )
    report = InstallConformanceRunner(platform_root).run()
    assert report.exit_code == 1
    outcomes = _outcomes(platform_root)
    assert outcomes["install/parity::manifest-teams-bijection"] is TestOutcome.FAILED


def test_folder_without_a_manifest_entry_fails_the_bijection(platform_root: Path) -> None:
    stray = platform_root / "teams" / "stray-app"
    stray.mkdir()
    (stray / "namespace.yaml").write_text("kind: Namespace\n", encoding="utf-8")
    outcomes = _outcomes(platform_root)
    assert outcomes["install/parity::manifest-teams-bijection"] is TestOutcome.FAILED


def test_application_pointed_off_the_deploy_branch_fails(platform_root: Path) -> None:
    application = platform_root / "teams" / "alpha-app" / "application.yaml"
    application.write_text(
        application.read_text(encoding="utf-8").replace(
            "targetRevision: deploy-test", "targetRevision: main"
        ),
        encoding="utf-8",
    )
    outcomes = _outcomes(platform_root)
    assert outcomes["install/delivery::argocd-application[alpha-app]"] is TestOutcome.FAILED
    # The neighbour's row stays green: the failure is attributed per app.
    assert outcomes["install/delivery::argocd-application[beta-app]"] is TestOutcome.PASSED


def test_unclean_database_job_fails_isolation(platform_root: Path) -> None:
    jobs = platform_root / "teams" / "beta-app" / "jobs.yaml"
    jobs.write_text(
        jobs.read_text(encoding="utf-8").replace(
            "secretName: pg-app-beta-app", "secretName: pg-app"
        ),
        encoding="utf-8",
    )
    outcomes = _outcomes(platform_root)
    assert outcomes["install/database::isolation-clean[beta-app]"] is TestOutcome.FAILED


def test_missing_zone_fails_and_mcp_rows_follow(platform_root: Path) -> None:
    (platform_root / "values.yaml").write_text("operators: []\n", encoding="utf-8")
    outcomes = _outcomes(platform_root)
    assert outcomes["install/values::zone-declared"] is TestOutcome.FAILED
    assert outcomes["install/mcp::derived-endpoint[alpha-app]"] is TestOutcome.FAILED


@intent("INT-PROMOTE-002")
def test_bindings_matching_the_deploy_values_pass(platform_root: Path) -> None:
    """INT-PROMOTE-002: with readable deploy values carrying exactly the bound
    tag paths, the values-bound row passes; the values are read off each
    Application's own source (repo, deploy branch, prod/values.yaml)."""
    source = _StaticRepo(
        {
            "alpha-app": {"image": {"tag": "1.2.3"}},
            "beta-app": {"image": {"tag": "1.2.3"}},
        }
    )
    report = InstallConformanceRunner(platform_root, source, act_rows=True).run()
    outcomes = {result.node_id: result.outcome for result in report.results}
    assert outcomes["install/promotion::image-updater-promotes[alpha-app]"] is TestOutcome.PASSED
    assert outcomes["install/promotion::image-updater-promotes[beta-app]"] is TestOutcome.PASSED
    assert report.exit_code == 0
    assert (
        "https://github.com/Test-Org/alpha-app",
        "deploy-test",
        "prod/values.yaml",
    ) in source.calls


@intent("INT-LIFECYCLE-002")
def test_a_frozen_app_keeps_every_promotion_row_green(platform_root: Path) -> None:
    """INT-LIFECYCLE-002: the freeze adds only alias tag filters, so the whole
    binding survives and all three promotion rows stay verified. This is what
    makes freezing gate-compatible where dropping the annotations would not
    be: an Application with no image-list earns no promotion rows at all, and
    the never-promotes class those rows exist to catch would go unwatched."""
    application = platform_root / "teams" / "alpha-app" / "application.yaml"
    application.write_text(
        freeze_application_promotion(application.read_text(encoding="utf-8"), app="alpha-app"),
        encoding="utf-8",
    )
    source = _StaticRepo(
        {"alpha-app": {"image": {"tag": "1.2.3"}}, "beta-app": {"image": {"tag": "1.2.3"}}},
        default_branch="main",
        build_workflow=_CI_CALLER,
        deploy_paths=_ENV_CONFIG,
        # The default branch's listing answers without docs/Dockerfile.
        default_paths=frozenset(),
        compose={"alpha-app": "services:\n  app:\n    build: .\n    image: alpha-app\n"},
    )
    outcomes = {
        result.node_id: result.outcome
        for result in InstallConformanceRunner(platform_root, source, act_rows=True)
        .run()
        .results
    }
    assert outcomes["install/promotion::image-updater-coherent[alpha-app]"] is TestOutcome.PASSED
    assert outcomes["install/promotion::image-updater-promotes[alpha-app]"] is TestOutcome.PASSED
    assert (
        outcomes["install/promotion::image-updater-released-set[alpha-app]"]
        is TestOutcome.PASSED
    )


@intent("INT-PROMOTE-002")
def test_single_image_bindings_on_a_multi_image_app_fail(platform_root: Path) -> None:
    """INT-PROMOTE-002: deploy values releasing several images (tags under
    <app>.images.<component>) fail a single-image binding in both directions:
    the bound path is not in the values, and the released tags are unbound.
    This is the silent never-promotes state, surfaced as a red row."""
    source = _StaticRepo(
        {
            "alpha-app": {"images": {"server": {"tag": "1.0.0"}, "docs": {"tag": "1.0.0"}}},
            "beta-app": {"image": {"tag": "1.0.0"}},
        }
    )
    report = InstallConformanceRunner(platform_root, source, act_rows=True).run()
    outcomes = {result.node_id: result.outcome for result in report.results}
    assert outcomes["install/promotion::image-updater-promotes[alpha-app]"] is TestOutcome.FAILED
    assert outcomes["install/promotion::image-updater-promotes[beta-app]"] is TestOutcome.PASSED
    assert report.exit_code == 1


@intent("INT-PROMOTE-002")
def test_deploy_values_are_read_once_across_a_gate_pair(platform_root: Path) -> None:
    """INT-PROMOTE-002: a gate diffs a baseline run against a candidate run
    seconds apart, so both must judge the same values snapshot - a fetch that
    fails in one run but succeeds in the other would turn a pre-existing
    values-row failure into a new one and refuse an unrelated change. The
    runner caches deploy-values reads across runs."""
    source = _StaticRepo(
        {
            "alpha-app": {"image": {"tag": "1.2.3"}},
            "beta-app": {"image": {"tag": "1.2.3"}},
        }
    )
    runner = InstallConformanceRunner(platform_root, source, act_rows=True)
    runner.run()
    calls_after_first = len(source.calls)
    runner.run()
    assert len(source.calls) == calls_after_first


@intent("INT-PROMOTE-002")
def test_unreadable_deploy_values_report_skipped_never_passed(platform_root: Path) -> None:
    """INT-PROMOTE-002: a deploy branch the source cannot read (not stood up
    yet, host unreachable) reports the values-bound row skipped - honest,
    distinguishable from verified, and never red."""
    report = InstallConformanceRunner(platform_root, _StaticRepo(None), act_rows=True).run()
    outcomes = {result.node_id: result.outcome for result in report.results}
    assert outcomes["install/promotion::image-updater-promotes[alpha-app]"] is TestOutcome.SKIPPED
    assert report.exit_code == 0


@intent("INT-PROMOTE-002")
def test_alias_watching_a_foreign_package_fails_coherence(platform_root: Path) -> None:
    """INT-PROMOTE-002: an image-list entry outside the app repo's GHCR owner
    watches a package the app's CI cannot publish, so the coherence row fails."""
    application = platform_root / "teams" / "alpha-app" / "application.yaml"
    application.write_text(
        application.read_text(encoding="utf-8").replace(
            "app=ghcr.io/test-org/alpha-app", "app=ghcr.io/someone-else/alpha-app"
        ),
        encoding="utf-8",
    )
    outcomes = _outcomes(platform_root)
    assert outcomes["install/promotion::image-updater-coherent[alpha-app]"] is TestOutcome.FAILED
    assert outcomes["install/promotion::image-updater-coherent[beta-app]"] is TestOutcome.PASSED


@intent("INT-PROMOTE-002")
def test_alias_without_helm_bindings_fails_coherence(platform_root: Path) -> None:
    """INT-PROMOTE-002: an image-list alias with no helm image-tag path has
    nowhere to write its updates, so the coherence row fails."""
    application = platform_root / "teams" / "alpha-app" / "application.yaml"
    application.write_text(
        application.read_text(encoding="utf-8").replace(
            "    argocd-image-updater.argoproj.io/app.helm.image-tag: alpha-app.image.tag\n",
            "",
        ),
        encoding="utf-8",
    )
    outcomes = _outcomes(platform_root)
    assert outcomes["install/promotion::image-updater-coherent[alpha-app]"] is TestOutcome.FAILED


@intent("INT-PROMOTE-002")
def test_canonical_multi_image_bindings_pass_both_rows(platform_root: Path) -> None:
    """INT-PROMOTE-002: the canonical multi-image shape - one alias per
    component, package <app>-<component>, paths <app>.images.<component>.* -
    passes the shape row, and passes the values row against deploy values
    carrying exactly those tags."""
    application = platform_root / "teams" / "alpha-app" / "application.yaml"
    text = application.read_text(encoding="utf-8")
    text = text.replace(
        "    argocd-image-updater.argoproj.io/image-list: app=ghcr.io/test-org/alpha-app\n"
        "    argocd-image-updater.argoproj.io/app.update-strategy: semver\n"
        "    argocd-image-updater.argoproj.io/app.helm.image-name: alpha-app.image.repository\n"
        "    argocd-image-updater.argoproj.io/app.helm.image-tag: alpha-app.image.tag\n",
        "    argocd-image-updater.argoproj.io/image-list: "
        "api=ghcr.io/test-org/alpha-app-api,web=ghcr.io/test-org/alpha-app-web\n"
        "    argocd-image-updater.argoproj.io/api.update-strategy: semver\n"
        "    argocd-image-updater.argoproj.io/api.helm.image-name: "
        "alpha-app.images.api.repository\n"
        "    argocd-image-updater.argoproj.io/api.helm.image-tag: alpha-app.images.api.tag\n"
        "    argocd-image-updater.argoproj.io/web.update-strategy: semver\n"
        "    argocd-image-updater.argoproj.io/web.helm.image-name: "
        "alpha-app.images.web.repository\n"
        "    argocd-image-updater.argoproj.io/web.helm.image-tag: alpha-app.images.web.tag\n",
    )
    application.write_text(text, encoding="utf-8")
    source = _StaticRepo(
        {
            "alpha-app": {"images": {"api": {"tag": "2.0.0"}, "web": {"tag": "2.0.0"}}},
            "beta-app": {"image": {"tag": "1.0.0"}},
        }
    )
    report = InstallConformanceRunner(platform_root, source, act_rows=True).run()
    outcomes = {result.node_id: result.outcome for result in report.results}
    assert outcomes["install/promotion::image-updater-coherent[alpha-app]"] is TestOutcome.PASSED
    assert outcomes["install/promotion::image-updater-promotes[alpha-app]"] is TestOutcome.PASSED


@intent("INT-PROMOTE-002")
def test_off_canonical_layout_fails_shape_while_its_values_row_passes(
    platform_root: Path,
) -> None:
    """INT-PROMOTE-002: a bespoke values layout (<app>.<component>.image.*)
    whose bindings do match its own deploy values is shape drift, not broken
    promotion: the shape row fails, the values row passes. Two different
    findings, reported apart."""
    application = platform_root / "teams" / "alpha-app" / "application.yaml"
    text = application.read_text(encoding="utf-8")
    text = text.replace(
        "    argocd-image-updater.argoproj.io/image-list: app=ghcr.io/test-org/alpha-app\n"
        "    argocd-image-updater.argoproj.io/app.update-strategy: semver\n"
        "    argocd-image-updater.argoproj.io/app.helm.image-name: alpha-app.image.repository\n"
        "    argocd-image-updater.argoproj.io/app.helm.image-tag: alpha-app.image.tag\n",
        "    argocd-image-updater.argoproj.io/image-list: "
        "api=ghcr.io/test-org/alpha-app-api,web=ghcr.io/test-org/alpha-app-web\n"
        "    argocd-image-updater.argoproj.io/api.update-strategy: semver\n"
        "    argocd-image-updater.argoproj.io/api.helm.image-name: alpha-app.api.image.repository\n"
        "    argocd-image-updater.argoproj.io/api.helm.image-tag: alpha-app.api.image.tag\n"
        "    argocd-image-updater.argoproj.io/web.update-strategy: semver\n"
        "    argocd-image-updater.argoproj.io/web.helm.image-name: alpha-app.web.image.repository\n"
        "    argocd-image-updater.argoproj.io/web.helm.image-tag: alpha-app.web.image.tag\n",
    )
    application.write_text(text, encoding="utf-8")
    source = _StaticRepo(
        {
            "alpha-app": {
                "api": {"image": {"tag": "2.0.0"}},
                "web": {"image": {"tag": "2.0.0"}},
            },
            "beta-app": {"image": {"tag": "1.0.0"}},
        }
    )
    report = InstallConformanceRunner(platform_root, source, act_rows=True).run()
    outcomes = {result.node_id: result.outcome for result in report.results}
    assert outcomes["install/promotion::image-updater-coherent[alpha-app]"] is TestOutcome.FAILED
    assert outcomes["install/promotion::image-updater-promotes[alpha-app]"] is TestOutcome.PASSED


@intent("INT-PROMOTE-003")
def test_alias_set_matching_the_released_set_passes(platform_root: Path) -> None:
    """INT-PROMOTE-003: a compose whose build: services release exactly the
    watched packages (named by their image:, no docs image) passes the
    released-set row, read off each app repo's default branch."""
    source = _StaticRepo(
        default_branch="main",
        build_workflow=_CI_CALLER,
        # The default branch's listing answers without docs/Dockerfile.
        default_paths=frozenset(),
        compose={
            "alpha-app": "services:\n  site:\n    build: ..\n    image: alpha-app:latest\n",
            "beta-app": "services:\n  site:\n    build: ..\n    image: beta-app:latest\n",
        },
    )
    report = InstallConformanceRunner(platform_root, source, act_rows=True).run()
    outcomes = {result.node_id: result.outcome for result in report.results}
    assert (
        outcomes["install/promotion::image-updater-released-set[alpha-app]"]
        is TestOutcome.PASSED
    )
    assert (
        outcomes["install/promotion::image-updater-released-set[beta-app]"]
        is TestOutcome.PASSED
    )
    # No docs/Dockerfile on either repo: the docs-image act row fails, which
    # is the standing rule (no docs, no onboard) and the reason this report
    # is not exit 0.
    assert outcomes["install/onboarding::docs-image[alpha-app]"] is TestOutcome.FAILED
    assert report.exit_code == 1


@intent("INT-PROMOTE-003")
def test_phantom_alias_fails_the_released_set_row(platform_root: Path) -> None:
    """INT-PROMOTE-003: a repo releasing alpha-app-api while the alias
    watches the bare package alpha-app fails the row in both directions -
    the alias is phantom and the released image is unwatched - and the
    values-bound legs cannot catch it, since a phantom binding's path can
    sit in the deploy values while nothing ever writes it."""
    source = _StaticRepo(
        default_branch="main",
        build_workflow=_CI_CALLER,
        # The default branch's listing answers without docs/Dockerfile.
        default_paths=frozenset(),
        compose={
            "alpha-app": "services:\n  api:\n    build: ..\n    image: alpha-app-api:latest\n",
            "beta-app": "services:\n  site:\n    build: ..\n    image: beta-app:latest\n",
        },
    )
    report = InstallConformanceRunner(platform_root, source, act_rows=True).run()
    outcomes = {result.node_id: result.outcome for result in report.results}
    assert (
        outcomes["install/promotion::image-updater-released-set[alpha-app]"]
        is TestOutcome.FAILED
    )
    assert (
        outcomes["install/promotion::image-updater-released-set[beta-app]"]
        is TestOutcome.PASSED
    )
    assert report.exit_code == 1


@intent("INT-PROMOTE-003")
def test_released_docs_image_with_no_alias_fails(platform_root: Path) -> None:
    """INT-PROMOTE-003: docs/Dockerfile makes CI publish <app>-docs beside
    the compose services, so a repo shipping docs while no docs alias
    watches them fails the row: the docs image would pin its first tag
    forever while CI keeps releasing."""
    source = _StaticRepo(
        default_branch="main",
        build_workflow=_CI_CALLER,
        # The default branch's listing answers without docs/Dockerfile, so
        # beta's empty docs read is a verified absence.
        default_paths=frozenset(),
        compose={
            "alpha-app": "services:\n  site:\n    build: ..\n    image: alpha-app:latest\n",
            "beta-app": "services:\n  site:\n    build: ..\n    image: beta-app:latest\n",
        },
        docs_dockerfile={"alpha-app": "FROM nginx:1.27-alpine\n"},
    )
    report = InstallConformanceRunner(platform_root, source, act_rows=True).run()
    outcomes = {result.node_id: result.outcome for result in report.results}
    assert (
        outcomes["install/promotion::image-updater-released-set[alpha-app]"]
        is TestOutcome.FAILED
    )
    assert (
        outcomes["install/promotion::image-updater-released-set[beta-app]"]
        is TestOutcome.PASSED
    )
    # The docs act row reads the same docs/Dockerfile: present for alpha,
    # absent for beta.
    assert outcomes["install/onboarding::docs-image[alpha-app]"] is TestOutcome.PASSED
    assert outcomes["install/onboarding::docs-image[beta-app]"] is TestOutcome.FAILED


@intent("INT-PROMOTE-003")
def test_an_unanswered_docs_read_skips_the_act_rows_it_feeds(platform_root: Path) -> None:
    """INT-PROMOTE-003, #42: an empty docs/Dockerfile read is judged absent only
    when the default branch's listing answers without the file. A listing that
    carries it means the read went unanswered (a timeout or a reset connection
    under the bulk prefetch), so the docs-image row and the released set it
    feeds report skipped rather than failing the act."""
    source = _StaticRepo(
        default_branch="main",
        build_workflow=_CI_CALLER,
        default_paths=frozenset({"docs/Dockerfile"}),
        compose={
            "alpha-app": "services:\n  site:\n    build: ..\n    image: alpha-app:latest\n",
            "beta-app": "services:\n  site:\n    build: ..\n    image: beta-app:latest\n",
        },
    )
    report = InstallConformanceRunner(platform_root, source, act_rows=True).run()
    rows = {result.node_id: result for result in report.results}
    docs_row = rows["install/onboarding::docs-image[alpha-app]"]
    assert docs_row.outcome is TestOutcome.SKIPPED
    assert "docs/Dockerfile on main could not be read" in docs_row.detail
    assert (
        rows["install/promotion::image-updater-released-set[alpha-app]"].outcome
        is TestOutcome.SKIPPED
    )


@intent("INT-PROMOTE-004")
def test_failing_released_set_row_names_the_mismatch_and_the_derived_set(
    platform_root: Path,
) -> None:
    """INT-PROMOTE-004: the row that fails over an unwatched docs image says
    which package is unwatched, names the whole derived set, and names the two
    files it derived it from - all of it in the report output the gate's
    rejection prints, so the caller never has to go looking in GHCR for a set
    this check reads off the app repo."""
    source = _StaticRepo(
        default_branch="main",
        build_workflow=_CI_CALLER,
        compose={
            "alpha-app": "services:\n  site:\n    build: ..\n    image: alpha-app:latest\n",
            "beta-app": "services:\n  site:\n    build: ..\n    image: beta-app:latest\n",
        },
        docs_dockerfile={"alpha-app": "FROM nginx:1.27-alpine\n"},
    )
    report = InstallConformanceRunner(platform_root, source, act_rows=True).run()
    row = next(
        result
        for result in report.results
        if result.node_id == "install/promotion::image-updater-released-set[alpha-app]"
    )
    assert row.outcome is TestOutcome.FAILED
    assert "alpha-app-docs" in row.detail
    assert "no alias watches it" in row.detail
    assert "alpha-app, alpha-app-docs" in row.detail
    assert "devops/docker-compose.yml" in row.detail
    assert "docs/Dockerfile" in row.detail
    assert row.detail in report.output


@intent("INT-PROMOTE-004")
def test_passing_promotion_rows_carry_no_detail(platform_root: Path) -> None:
    """INT-PROMOTE-004: the detail is the failure's diagnostic, not a running
    commentary - a row that passes carries none, so the output stays a clean
    outcome list and every line with a colon on it is a finding."""
    source = _StaticRepo(
        default_branch="main",
        build_workflow=_CI_CALLER,
        # The default branch's listing answers without docs/Dockerfile.
        default_paths=frozenset(),
        compose={
            "alpha-app": "services:\n  site:\n    build: ..\n    image: alpha-app:latest\n",
            "beta-app": "services:\n  site:\n    build: ..\n    image: beta-app:latest\n",
        },
    )
    report = InstallConformanceRunner(platform_root, source, act_rows=True).run()
    passing = [
        result
        for result in report.results
        if result.node_id.startswith("install/promotion::")
        and result.outcome is TestOutcome.PASSED
    ]
    assert passing
    assert all(result.detail == "" for result in passing)
    for result in passing:
        assert f"{result.node_id} PASSED" in report.output


@intent("INT-PROMOTE-003")
def test_unreadable_compose_reports_the_released_set_row_skipped(
    platform_root: Path,
) -> None:
    """INT-PROMOTE-003: a readable repo whose compose cannot be read gives no
    released set to hold the aliases to; the row reports skipped, never
    passed, and never invents a verdict."""
    source = _StaticRepo(default_branch="main")
    report = InstallConformanceRunner(platform_root, source, act_rows=True).run()
    outcomes = {result.node_id: result.outcome for result in report.results}
    assert (
        outcomes["install/promotion::image-updater-released-set[alpha-app]"]
        is TestOutcome.SKIPPED
    )


@intent("INT-DELIVERY-001")
def test_shipping_app_repo_passes_both_delivery_rows(platform_root: Path) -> None:
    """INT-DELIVERY-001: a repo whose build.yml calls the shared reusable
    workflow and whose deploy branch carries the dev/ and prod/ env config
    passes both delivery rows, read off the repo host with no clone."""
    source = _StaticRepo(
        default_branch="main",
        build_workflow=_CI_CALLER,
        deploy_paths=_ENV_CONFIG,
    )
    report = InstallConformanceRunner(platform_root, source).run()
    outcomes = {result.node_id: result.outcome for result in report.results}
    assert outcomes["install/delivery::ci-caller[alpha-app]"] is TestOutcome.PASSED
    assert outcomes["install/delivery::deploy-branch[alpha-app]"] is TestOutcome.PASSED


@intent("INT-DELIVERY-001")
def test_hand_rolled_build_workflow_fails_the_ci_caller_row(platform_root: Path) -> None:
    """INT-DELIVERY-001: a readable build.yml that never calls the shared
    reusable workflow (a hand-rolled lint/test build, which publishes no
    image and no chart: the 2ez4tv defect) is verifiably wrong and fails."""
    source = _StaticRepo(
        default_branch="main",
        build_workflow="jobs:\n  lint:\n    runs-on: ubuntu-latest\n",
        deploy_paths=_ENV_CONFIG,
    )
    report = InstallConformanceRunner(platform_root, source).run()
    outcomes = {result.node_id: result.outcome for result in report.results}
    assert outcomes["install/delivery::ci-caller[alpha-app]"] is TestOutcome.FAILED
    assert outcomes["install/delivery::deploy-branch[alpha-app]"] is TestOutcome.PASSED
    assert report.exit_code == 1


@intent("INT-DELIVERY-001")
def test_missing_build_workflow_in_a_readable_repo_fails(platform_root: Path) -> None:
    """INT-DELIVERY-001: the app-repo contract requires the CI caller before
    onboarding, so a readable repo with no build.yml at all fails the row
    rather than hiding behind a skip."""
    source = _StaticRepo(
        default_branch="main",
        build_workflow=None,
        deploy_paths=_ENV_CONFIG,
        # The default branch's listing answers without build.yml: verified absent.
        default_paths=frozenset(),
    )
    report = InstallConformanceRunner(platform_root, source).run()
    outcomes = {result.node_id: result.outcome for result in report.results}
    assert outcomes["install/delivery::ci-caller[alpha-app]"] is TestOutcome.FAILED
    assert report.exit_code == 1


@intent("INT-DELIVERY-001")
def test_an_unanswered_build_workflow_read_reports_skipped(platform_root: Path) -> None:
    """INT-DELIVERY-001, #42: under the bulk prefetch a build.yml read can go
    unanswered (a timeout, a reset connection) while the file sits on the
    default branch. The listing carries it, so the row reports skipped, naming
    the read, and the report stays green."""
    source = _StaticRepo(
        default_branch="main",
        build_workflow=None,
        deploy_paths=_ENV_CONFIG,
        default_paths=frozenset({".github/workflows/build.yml"}),
    )
    report = InstallConformanceRunner(platform_root, source).run()
    rows = {result.node_id: result for result in report.results}
    row = rows["install/delivery::ci-caller[alpha-app]"]
    assert row.outcome is TestOutcome.SKIPPED
    assert ".github/workflows/build.yml on main could not be read" in row.detail
    assert report.exit_code == 0


@intent("INT-DELIVERY-001")
def test_an_empty_build_workflow_read_with_no_listing_reports_skipped(
    platform_root: Path,
) -> None:
    """INT-DELIVERY-001, #42: when neither the build.yml read nor the default
    branch's listing answers, nothing verifies the file is missing, so the row
    reports skipped, never failed."""
    source = _StaticRepo(
        default_branch="main",
        build_workflow=None,
        deploy_paths=_ENV_CONFIG,
    )
    report = InstallConformanceRunner(platform_root, source).run()
    outcomes = {result.node_id: result.outcome for result in report.results}
    assert outcomes["install/delivery::ci-caller[alpha-app]"] is TestOutcome.SKIPPED
    assert report.exit_code == 0


@intent("INT-DELIVERY-001")
def test_deploy_branch_missing_env_config_fails(platform_root: Path) -> None:
    """INT-DELIVERY-001: a deploy branch that exists without the full dev/ and
    prod/ env config gives ArgoCD nothing to deliver; present-but-wrong is
    verifiably wrong, so the row fails while the CI row stays green."""
    source = _StaticRepo(
        default_branch="main",
        build_workflow=_CI_CALLER,
        deploy_paths=frozenset({"prod/values.yaml"}),
    )
    report = InstallConformanceRunner(platform_root, source).run()
    outcomes = {result.node_id: result.outcome for result in report.results}
    assert outcomes["install/delivery::deploy-branch[alpha-app]"] is TestOutcome.FAILED
    assert outcomes["install/delivery::ci-caller[alpha-app]"] is TestOutcome.PASSED
    assert report.exit_code == 1


@intent("INT-DELIVERY-001")
def test_unreadable_delivery_legs_report_skipped_never_passed(platform_root: Path) -> None:
    """INT-DELIVERY-001: an app repo the source cannot read and a deploy
    branch not yet stood up report both rows skipped - honest, distinguishable
    from verified, and never red - so a greenfield onboarding is not refused
    over the branch the runbook stands up only after the merge."""
    report = InstallConformanceRunner(platform_root, _StaticRepo(None)).run()
    outcomes = {result.node_id: result.outcome for result in report.results}
    assert outcomes["install/delivery::ci-caller[alpha-app]"] is TestOutcome.SKIPPED
    assert outcomes["install/delivery::deploy-branch[alpha-app]"] is TestOutcome.SKIPPED
    assert report.exit_code == 0


@intent("INT-DELIVERY-001")
def test_a_repo_the_host_denies_fails_its_own_row_naming_it(platform_root: Path) -> None:
    """INT-DELIVERY-001: a host answering that the repository is not there for
    the studio is a definite fact about one artifact, so the app-repo row goes
    red and carries the repository it read. Onboarding an app under a name no
    repository carries lands exactly here, instead of four skipped legs each
    naming a different artifact to stand up."""
    report = InstallConformanceRunner(platform_root, _StaticRepo(repo_exists=False)).run()
    rows = {result.node_id: result for result in report.results}
    row = rows["install/delivery::app-repo-readable[alpha-app]"]
    assert row.outcome is TestOutcome.FAILED
    assert "https://github.com/Test-Org/alpha-app" in row.detail
    assert "'alpha-app'" in row.detail
    assert report.exit_code == 1


@intent("INT-DELIVERY-001")
def test_an_unreachable_repo_host_reports_the_app_repo_row_skipped(
    platform_root: Path,
) -> None:
    """INT-DELIVERY-001: an answer that proves nothing (host unreachable,
    credentials rejected, no source wired) reports skipped, never red - a
    greenfield onboarding is never refused over an artifact the runbook stands
    up after the merge, and the row still names the repository it tried."""
    report = InstallConformanceRunner(platform_root, _StaticRepo(None)).run()
    rows = {result.node_id: result for result in report.results}
    row = rows["install/delivery::app-repo-readable[alpha-app]"]
    assert row.outcome is TestOutcome.SKIPPED
    assert "https://github.com/Test-Org/alpha-app" in row.detail
    assert report.exit_code == 0


@intent("INT-DELIVERY-001")
def test_a_visible_repo_passes_the_app_repo_row(platform_root: Path) -> None:
    """INT-DELIVERY-001: a repository the host serves passes its own row, so
    the legs that read through it are judged on their own artifacts."""
    report = InstallConformanceRunner(platform_root, _StaticRepo(repo_exists=True)).run()
    outcomes = {result.node_id: result.outcome for result in report.results}
    assert outcomes["install/delivery::app-repo-readable[alpha-app]"] is TestOutcome.PASSED
    assert outcomes["install/delivery::ci-caller[alpha-app]"] is TestOutcome.SKIPPED
    assert report.exit_code == 0


def test_unreadable_manifest_is_a_broken_suite_not_a_pass(platform_root: Path) -> None:
    """A checkout the runner cannot judge reports a suite-level error (exit 2),
    which the gate treats as failing; it never reads as a green run."""
    (platform_root / "foundry.yaml").write_text(
        "parts: [broken\n  - not yaml", encoding="utf-8"
    )
    report = InstallConformanceRunner(platform_root).run()
    assert report.exit_code == 2
    assert report.results == ()


_CHART_WITH_IDENTITY = """auth:
  oidc:
    enabled: true
    existingSecret: keycloak-alpha-app
"""

_CHART_WITH_BOTH = """auth:
  existingSecret: alpha-app-auth
  oidc:
    existingSecret: keycloak-alpha-app
postgres:
  existingSecret: pg-app-alpha-app
"""

_CHART_WITH_NO_PLATFORM_CREDENTIAL = """auth:
  existingSecret: alpha-app-auth
app:
  port: 8000
"""


def _grant_identity(platform_root: Path, app: str) -> None:
    """The provide side: the generate-if-absent Job the grant renders."""
    jobs = platform_root / "teams" / app / "jobs.yaml"
    existing = jobs.read_text(encoding="utf-8") if jobs.is_file() else ""
    jobs.write_text(
        f"{existing}---\napiVersion: batch/v1\nkind: Job\nmetadata:\n"
        f"  name: gen-keycloak-{app}\n  namespace: {app}\n",
        encoding="utf-8",
    )


@intent("INT-GRANT-004")
def test_chart_demanding_an_ungranted_credential_fails(platform_root: Path) -> None:
    """INT-GRANT-004: a chart naming keycloak-<app> with no grant in
    teams/<app>/ to mint it fails the row. The pod would wait forever on a
    Secret nothing creates, and nothing else in the pipeline goes red."""
    source = _StaticRepo(
        values={},
        default_branch="main",
        chart_values={"alpha-app": _CHART_WITH_IDENTITY},
    )
    report = InstallConformanceRunner(platform_root, source).run()
    outcomes = {result.node_id: result.outcome for result in report.results}
    assert outcomes["install/credentials::demand-grant[alpha-app]"] is TestOutcome.FAILED
    assert report.exit_code == 1


@intent("INT-GRANT-004")
def test_chart_demand_matched_by_its_grant_passes(platform_root: Path) -> None:
    """INT-GRANT-004: the same chart passes once teams/<app>/ carries the
    gen-keycloak-<app> generator that mints what it names."""
    _grant_identity(platform_root, "alpha-app")
    source = _StaticRepo(
        values={},
        default_branch="main",
        chart_values={"alpha-app": _CHART_WITH_IDENTITY},
    )
    report = InstallConformanceRunner(platform_root, source).run()
    outcomes = {result.node_id: result.outcome for result in report.results}
    assert outcomes["install/credentials::demand-grant[alpha-app]"] is TestOutcome.PASSED


@intent("INT-GRANT-004")
def test_each_demanded_credential_is_judged_independently(platform_root: Path) -> None:
    """INT-GRANT-004: granting identity does not excuse an ungranted
    database; the row holds every credential the chart names."""
    _grant_identity(platform_root, "alpha-app")
    source = _StaticRepo(
        values={},
        default_branch="main",
        chart_values={"alpha-app": _CHART_WITH_BOTH},
    )
    report = InstallConformanceRunner(platform_root, source).run()
    outcomes = {result.node_id: result.outcome for result in report.results}
    assert outcomes["install/credentials::demand-grant[alpha-app]"] is TestOutcome.FAILED


@intent("INT-GRANT-004")
def test_chart_naming_no_platform_credential_is_vacuously_clean(
    platform_root: Path,
) -> None:
    """INT-GRANT-004: an app-owned secret (an external fact the operator
    applies) is not a platform-minted credential and demands no grant."""
    source = _StaticRepo(
        values={},
        default_branch="main",
        build_workflow=_CI_CALLER,
        chart_values={"alpha-app": _CHART_WITH_NO_PLATFORM_CREDENTIAL},
    )
    report = InstallConformanceRunner(platform_root, source).run()
    outcomes = {result.node_id: result.outcome for result in report.results}
    assert outcomes["install/credentials::demand-grant[alpha-app]"] is TestOutcome.PASSED
    assert report.exit_code == 0


_CHART_WITH_INVENTED_NAMES = """auth:
  existingSecret: alpha-app-oidc
database:
  existingSecret: alpha-app-db
"""

_CHART_WITH_IDENTITY_DORMANT = """auth:
  oidc:
    enabled: false
    existingSecret: keycloak-alpha-app
"""

_CHART_NAMING_SECRET_UNDER_PLAIN_KEY = """database:
  secret: pg-app-alpha-app
"""


def _grant_database(platform_root: Path, app: str) -> None:
    """The provide side of the database grant."""
    jobs = platform_root / "teams" / app / "jobs.yaml"
    existing = jobs.read_text(encoding="utf-8") if jobs.is_file() else ""
    jobs.write_text(
        f"{existing}---\napiVersion: batch/v1\nkind: Job\nmetadata:\n"
        f"  name: gen-pg-app-{app}\n  namespace: {app}\n",
        encoding="utf-8",
    )


@intent("INT-GRANT-004")
def test_grant_whose_credential_the_chart_never_names_fails(platform_root: Path) -> None:
    """INT-GRANT-004: a chart that substituted its own names for the
    platform's fails the row.

    The direction the demand side structurally cannot see: `alpha-app-oidc`
    matches no platform credential, so demand-only judging finds nothing to
    hold and passes green over a pod that never starts. This is how
    knight-fight served 503 for sixteen hours with every git-side row green.
    """
    _grant_identity(platform_root, "alpha-app")
    _grant_database(platform_root, "alpha-app")
    source = _StaticRepo(
        values={},
        default_branch="main",
        chart_values={"alpha-app": _CHART_WITH_INVENTED_NAMES},
    )
    report = InstallConformanceRunner(platform_root, source).run()
    outcomes = {result.node_id: result.outcome for result in report.results}
    assert outcomes["install/credentials::demand-grant[alpha-app]"] is TestOutcome.FAILED
    detail = next(
        r.detail
        for r in report.results
        if r.node_id == "install/credentials::demand-grant[alpha-app]"
    )
    assert "keycloak-alpha-app" in detail and "pg-app-alpha-app" in detail


@intent("INT-GRANT-004")
def test_granted_capability_left_dormant_fails(platform_root: Path) -> None:
    """INT-GRANT-004: naming the right credential under a block turned
    enabled: false consumes nothing, so a granted capability still fails."""
    _grant_identity(platform_root, "alpha-app")
    source = _StaticRepo(
        values={},
        default_branch="main",
        chart_values={"alpha-app": _CHART_WITH_IDENTITY_DORMANT},
    )
    report = InstallConformanceRunner(platform_root, source).run()
    outcomes = {result.node_id: result.outcome for result in report.results}
    assert outcomes["install/credentials::demand-grant[alpha-app]"] is TestOutcome.FAILED


@intent("INT-GRANT-004")
def test_dormant_block_without_its_grant_is_clean(platform_root: Path) -> None:
    """INT-GRANT-004: the scaffold ships both blocks off, carrying the correct
    names. Until the grant exists that is dormant, not a demand - otherwise
    every freshly scaffolded repo would fail the row on day one."""
    source = _StaticRepo(
        values={},
        default_branch="main",
        build_workflow=_CI_CALLER,
        chart_values={"alpha-app": _CHART_WITH_IDENTITY_DORMANT},
    )
    report = InstallConformanceRunner(platform_root, source).run()
    outcomes = {result.node_id: result.outcome for result in report.results}
    assert outcomes["install/credentials::demand-grant[alpha-app]"] is TestOutcome.PASSED


@intent("INT-GRANT-004")
def test_credential_named_under_a_plain_secret_key_is_seen(platform_root: Path) -> None:
    """INT-GRANT-004: `database.secret` names the credential as surely as
    `existingSecret` does. Three live charts use that spelling, and reading
    only one key name made them invisible to both directions of the check."""
    _grant_database(platform_root, "alpha-app")
    source = _StaticRepo(
        values={},
        default_branch="main",
        build_workflow=_CI_CALLER,
        chart_values={"alpha-app": _CHART_NAMING_SECRET_UNDER_PLAIN_KEY},
    )
    report = InstallConformanceRunner(platform_root, source).run()
    outcomes = {result.node_id: result.outcome for result in report.results}
    assert outcomes["install/credentials::demand-grant[alpha-app]"] is TestOutcome.PASSED


_CHART_WITH_EVENTS = """events:
  enabled: true
  seedSecret: nats-alpha-app
  jwtSecret: nats-jwt-alpha-app
"""


def _grant_events(platform_root: Path, app: str) -> None:
    """The provide side of the event-bus grant: the app's key generator."""
    jobs = platform_root / "teams" / app / "jobs.yaml"
    existing = jobs.read_text(encoding="utf-8") if jobs.is_file() else ""
    jobs.write_text(
        f"{existing}---\napiVersion: batch/v1\nkind: Job\nmetadata:\n"
        f"  name: gen-nats-{app}\n  namespace: {app}\n",
        encoding="utf-8",
    )


@intent("INT-GRANT-004")
def test_chart_demanding_an_ungranted_bus_seed_fails(platform_root: Path) -> None:
    """INT-GRANT-004: the event-bus seed is judged like the other two minted
    credentials. A chart naming nats-<app> with no gen-nats-<app> in
    teams/<app>/ schedules a pod that waits forever on a Secret nothing
    creates; the same chart passes once the generator is there."""
    source = _StaticRepo(
        values={},
        default_branch="main",
        chart_values={"alpha-app": _CHART_WITH_EVENTS},
    )
    report = InstallConformanceRunner(platform_root, source).run()
    outcomes = {result.node_id: result.outcome for result in report.results}
    assert outcomes["install/credentials::demand-grant[alpha-app]"] is TestOutcome.FAILED
    detail = next(
        r.detail
        for r in report.results
        if r.node_id == "install/credentials::demand-grant[alpha-app]"
    )
    assert "nats-alpha-app" in detail and "foundry-onboard-events" in detail

    _grant_events(platform_root, "alpha-app")
    report = InstallConformanceRunner(platform_root, source).run()
    outcomes = {result.node_id: result.outcome for result in report.results}
    assert outcomes["install/credentials::demand-grant[alpha-app]"] is TestOutcome.PASSED


@intent("INT-GRANT-004")
def test_bus_grant_whose_seed_the_chart_never_names_fails(platform_root: Path) -> None:
    """INT-GRANT-004: the grant-without-demand direction holds for the bus
    too: teams/<app>/ carrying gen-nats-<app> while the chart names no
    nats-<app> is the invented-name failure, invisible to demand-only judging."""
    _grant_events(platform_root, "alpha-app")
    source = _StaticRepo(
        values={},
        default_branch="main",
        chart_values={"alpha-app": _CHART_WITH_NO_PLATFORM_CREDENTIAL},
    )
    report = InstallConformanceRunner(platform_root, source).run()
    outcomes = {result.node_id: result.outcome for result in report.results}
    assert outcomes["install/credentials::demand-grant[alpha-app]"] is TestOutcome.FAILED
    detail = next(
        r.detail
        for r in report.results
        if r.node_id == "install/credentials::demand-grant[alpha-app]"
    )
    assert "nats-alpha-app" in detail


@intent("INT-GRANT-004")
def test_deploy_branch_enablement_counts_as_consuming(platform_root: Path) -> None:
    """INT-GRANT-004: a chart may default a capability off so it still installs
    standalone and let the deploy branch, where the credential exists, turn it
    on (shoot4fun). Judged on the chart default alone, that correct and live
    app would read as consuming nothing."""
    _grant_database(platform_root, "alpha-app")
    source = _StaticRepo(
        {"alpha-app": {"database": {"enabled": True}}},
        default_branch="main",
        build_workflow=_CI_CALLER,
        chart_values={"alpha-app": "database:\n  enabled: false\n  secret: pg-app-alpha-app\n"},
    )
    report = InstallConformanceRunner(platform_root, source).run()
    outcomes = {result.node_id: result.outcome for result in report.results}
    assert outcomes["install/credentials::demand-grant[alpha-app]"] is TestOutcome.PASSED


@intent("INT-GRANT-004")
def test_unreadable_chart_reports_the_credential_row_skipped(
    platform_root: Path,
) -> None:
    """INT-GRANT-004: an app repo the studio's token cannot read reports
    skipped, never passed - the demand side is team-owned and legitimately
    unreadable, and a guess here would read as verified."""
    report = InstallConformanceRunner(platform_root, _StaticRepo(None)).run()
    outcomes = {result.node_id: result.outcome for result in report.results}
    assert outcomes["install/credentials::demand-grant[alpha-app]"] is TestOutcome.SKIPPED
    assert report.exit_code == 0


@intent("INT-PROMOTE-005")
def test_app_side_drift_never_fails_the_standing_report(platform_root: Path) -> None:
    """INT-PROMOTE-005: the venue split. An app repo that grew a released
    image the aliases do not watch (the interim state between an app-side
    change and its reconcile_app) fails the ACT venue, where the caller can
    resolve it - and leaves the STANDING report green, because the standing
    suite judges only what the install itself owns. The same armed source,
    two venues, two verdicts, by design."""
    source = _StaticRepo(
        values={},
        default_branch="main",
        build_workflow=_CI_CALLER,
        deploy_paths=_ENV_CONFIG,
        compose={
            "alpha-app": (
                "services:\n"
                "  app:\n    build: ..\n    image: alpha-app:latest\n"
                "  api:\n    build: ..\n    image: alpha-app-api:latest\n"
            ),
            "beta-app": "services:\n  site:\n    build: ..\n    image: beta-app:latest\n",
        },
        docs_dockerfile={
            "alpha-app": "FROM nginx:1.27-alpine\n",
            "beta-app": "FROM nginx:1.27-alpine\n",
        },
    )
    standing = InstallConformanceRunner(platform_root, source).run()
    act = InstallConformanceRunner(platform_root, source, act_rows=True).run()
    standing_ids = {result.node_id for result in standing.results}
    act_outcomes = {result.node_id: result.outcome for result in act.results}
    assert standing.exit_code == 0
    assert "install/promotion::image-updater-released-set[alpha-app]" not in standing_ids
    assert "install/onboarding::docs-image[alpha-app]" not in standing_ids
    assert (
        act_outcomes["install/promotion::image-updater-released-set[alpha-app]"]
        is TestOutcome.FAILED
    )
    assert act_outcomes["install/onboarding::docs-image[alpha-app]"] is TestOutcome.PASSED
    assert act.exit_code == 1


# One app onboarded exactly as the studio itself would render it. Every leg the
# gate reads is a studio render keyed on the fixture install's own facts: the
# repository from create_app_repo's template, its deploy branch and its team
# folder from the renderers onboard_app runs. Nothing here is a hand-written
# stand-in for one of them, because a stand-in is precisely what stops a test
# from noticing that two renderers disagree.
_SCAFFOLD_APP = "delta-app"
_SCAFFOLD_DISPLAY = "Delta App"
_SCAFFOLD_DESCRIPTION = "The delta application"


def _onboard_a_scaffolded_app(platform_root: Path) -> _StaticRepo:
    """Render the whole contract for one new app; return its app-repo source.

    The install side (the manifest entry and teams/<app>/) lands in the
    checkout the runner reads; the app side (the chart values, the compose,
    the docs image, the CI caller, the deploy branch) is answered off the
    rendered scaffold and the rendered deploy branch.
    """
    app = _SCAFFOLD_APP
    registry = f"ghcr.io/{APP_REPO_ORG.lower()}"
    manifest_path = platform_root / "foundry.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    install_values = yaml.safe_load(
        (platform_root / "values.yaml").read_text(encoding="utf-8")
    )
    zone = str(install_values["zone"])
    environments = declared_environments(manifest)
    entry_env = entry_environment(environments)

    # The manifest entry: the tile facts, appended to the install's output role.
    manifest_path.write_text(
        manifest_path.read_text(encoding="utf-8")
        + f"- name: {app}\n  display: {_SCAFFOLD_DISPLAY}\n  icon: mdi-delta\n",
        encoding="utf-8",
    )
    folder = platform_root / "teams" / app
    folder.mkdir()
    for filename, text in render_team_skeleton(
        app=app,
        zone=zone,
        tunnel_id=str(install_values["tunnelId"]),
        install=str(manifest["install"]),
        operators=tuple(install_values["operators"]),
        entry_env=entry_env,
        image_components=SCAFFOLD_COMPONENTS,
    ):
        (folder / filename).write_text(text, encoding="utf-8")

    files = render_app_repo_scaffold(
        app=app,
        display_name=_SCAFFOLD_DISPLAY,
        description=_SCAFFOLD_DESCRIPTION,
        registry=registry,
    )
    deploy = dict(
        render_deploy_branch(
            app=app,
            registry=registry,
            components=SCAFFOLD_COMPONENTS,
            chart_version="1.0.0",
            image_tags={f"{app}-{component}": "1.0.0" for component in SCAFFOLD_COMPONENTS},
            zone=zone,
            environments=environments,
        )
    )
    return _StaticRepo(
        yaml.safe_load(deploy[f"{entry_env}/values.yaml"]),
        default_branch="main",
        build_workflow=files[".github/workflows/build.yml"],
        deploy_paths=frozenset(deploy),
        compose={app: files["devops/docker-compose.yml"]},
        docs_dockerfile={app: files["docs/Dockerfile"]},
        chart_values={app: files["k8s/values.yaml"]},
        repo_exists=True,
    )


@intent("INT-SCAFFOLD-003")
def test_a_freshly_scaffolded_repo_passes_the_onboarding_gate(platform_root: Path) -> None:
    """INT-SCAFFOLD-003: the studio's renders, judged by the studio's own gate.

    The act venue is the one onboard_app runs, so this is the admission
    decision itself: a repository born from create_app_repo, onboarded onto
    this install, either passes every row or the studio refuses the repository
    it just created. It refused discord-warden (2026-08-16, the first repo born
    from the current template): the scaffold ships `auth.oidc` with the sidecar
    off and an empty issuer, the deploy-branch renderer writes no issuer until
    a realm is granted, and the per-install row held every declared issuer to a
    pin - four surfaces of one contract, each green against its own idea of it.

    Skipped is asserted against as firmly as failed. Every leg here is readable
    by construction, so a skip would mean a row stopped reading the render it
    is meant to judge, and this test would go on passing over a gate that had
    quietly stopped looking.
    """
    source = _onboard_a_scaffolded_app(platform_root)
    for act_rows in (False, True):
        results = [
            result
            for result in InstallConformanceRunner(
                platform_root, source, act_rows=act_rows
            ).run().results
            if result.node_id.endswith(f"[{_SCAFFOLD_APP}]")
        ]
        assert results, "the scaffolded app earned no rows at all"
        offending = {
            result.node_id: result.detail
            for result in results
            if result.outcome is not TestOutcome.PASSED
        }
        assert not offending, f"act_rows={act_rows}: {offending}"
    # The row the incident named, called out so a regression cannot hide inside
    # the sweep above: the app serves this install's zone, and its dormant OIDC
    # block is not held to an issuer no sidecar would read.
    act = {
        result.node_id: result.outcome
        for result in InstallConformanceRunner(
            platform_root, source, act_rows=True
        ).run().results
    }
    assert act[f"install/parity::per-install-hostnames[{_SCAFFOLD_APP}]"] is TestOutcome.PASSED
