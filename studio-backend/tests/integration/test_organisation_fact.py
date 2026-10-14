"""The organisation is an install fact (INT-ORG-001).

Where an install's repositories live is read off its branch (githubOrgUrl,
platformRepo, ciRepo), the way its registry is, and every rendered repoURL,
GHCR owner, and scaffolded CI caller follows it. The studio's own fleet
default is consulted only by a branch that predates the fact.
"""

from __future__ import annotations

from pathlib import Path

from pytest_intent import intent

from studio.adapters.outbound.conformance_fs.install_conformance_runner import (
    InstallConformanceRunner,
)
from studio.adapters.outbound.platform_fs.fs_platform_repository import FsPlatformRepository
from studio.domain.model.install_organisation import InstallOrganisation
from studio.domain.services.app_repo_scaffold import render_app_repo_scaffold
from studio.domain.services.team_skeleton import APP_REPO_ORG, render_team_skeleton
from tests.integration.test_install_conformance import _ENV_CONFIG, _StaticRepo


def _skeleton(org: str) -> dict[str, str]:
    return dict(
        render_team_skeleton(
            app="gamma-app",
            zone="lab.example.dev",
            tunnel_id="00000000-0000-0000-0000-000000000000",
            install="test",
            operators=("operator@example.test",),
            entry_env="prod",
            image_components=("app", "docs"),
            org=org,
        )
    )


@intent("INT-ORG-001")
def test_the_branch_declares_where_its_repositories_live(platform_root: Path) -> None:
    """The fixture install names its organisation, platform repository, and
    CI repository; the fact reads back exactly as declared."""
    organisation = FsPlatformRepository(platform_root).organisation()
    assert organisation == InstallOrganisation(
        github_org="Test-Org", platform_repo="foundry-platform", ci_repo="ci"
    )
    assert organisation.declared
    assert organisation.org_or(APP_REPO_ORG) == "Test-Org"


@intent("INT-ORG-001")
def test_a_branch_predating_the_fact_falls_back_to_the_fleet_default(tmp_path: Path) -> None:
    """A values.yaml without the block is the shape of every branch founded
    before it: undeclared, so the fleet default the studio was built for
    stands in, which is what such a branch's rendered records already carry."""
    (tmp_path / "values.yaml").write_text("zone: lab.example.dev\n", encoding="utf-8")
    organisation = FsPlatformRepository(tmp_path).organisation()
    assert not organisation.declared
    assert organisation.org_or(APP_REPO_ORG) == APP_REPO_ORG
    assert organisation.ci_repo_or() == "ci"
    assert organisation.platform_repo_or() == "foundry-platform"

    application = _skeleton(org="")["application.yaml"]
    assert f"repoURL: https://github.com/{APP_REPO_ORG}/gamma-app" in application
    assert f"ghcr.io/{APP_REPO_ORG.lower()}/gamma-app-app" in application


@intent("INT-ORG-001")
def test_the_team_skeleton_renders_the_declared_organisation() -> None:
    """A declared organisation is the owner of the Application's repoURL and,
    absent a declared registry, of the GHCR packages Image Updater watches."""
    application = _skeleton(org="Test-Org")["application.yaml"]
    assert "repoURL: https://github.com/Test-Org/gamma-app" in application
    assert "app=ghcr.io/test-org/gamma-app-app,docs=ghcr.io/test-org/gamma-app-docs" in application
    assert APP_REPO_ORG not in application


@intent("INT-ORG-001")
def test_the_scaffold_calls_the_installs_own_ci_repository() -> None:
    """A fleet whose CI repository is prefixed scaffolds repos that call its
    own shared workflow, never another fleet's."""
    files = render_app_repo_scaffold(
        app="gamma-app",
        display_name="Gamma App",
        description="The gamma application",
        registry="ghcr.io/test-org",
        org="Test-Org",
        ci_repo="acme-ci",
    )
    build = files[".github/workflows/build.yml"]
    assert "uses: Test-Org/acme-ci/.github/workflows/build.yml@main" in build
    assert "lives once in Test-Org/acme-ci" in build
    assert APP_REPO_ORG not in build


@intent("INT-DELIVERY-001")
def test_the_shared_ci_repository_is_the_organisations_to_name(platform_root: Path) -> None:
    """The ci-caller row pins the owner and the reusable workflow's path, not
    the name of the repository carrying it: a prefixed CI repository under the
    same owner passes, and another owner's `ci` fails."""
    prefixed = "jobs:\n  build:\n    uses: Test-Org/acme-ci/.github/workflows/build.yml@main\n"
    report = InstallConformanceRunner(
        platform_root,
        _StaticRepo(default_branch="main", build_workflow=prefixed, deploy_paths=_ENV_CONFIG),
    ).run()
    outcomes = {result.node_id: result.outcome.value for result in report.results}
    assert outcomes["install/delivery::ci-caller[alpha-app]"] == "passed"

    foreign = "jobs:\n  build:\n    uses: Other-Org/ci/.github/workflows/build.yml@main\n"
    report = InstallConformanceRunner(
        platform_root,
        _StaticRepo(default_branch="main", build_workflow=foreign, deploy_paths=_ENV_CONFIG),
    ).run()
    outcomes = {result.node_id: result.outcome.value for result in report.results}
    assert outcomes["install/delivery::ci-caller[alpha-app]"] == "failed"
