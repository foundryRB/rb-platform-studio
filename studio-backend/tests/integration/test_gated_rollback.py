"""Gate-failure tests: the datastore is left byte-identical, nothing ships."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pytest_intent import intent

from studio.adapters.inbound.http.app import create_app
from studio.domain.exceptions.pr_failed_error import PrFailedError
from studio.domain.model.conformance_report import ConformanceReport
from studio.domain.model.test_outcome import TestOutcome
from tests.conftest import FakeGitPr, StubConformance, build_container, make_report


def _snapshot(platform_root: Path) -> dict[str, str]:
    return {
        path.relative_to(platform_root).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(platform_root.rglob("*"))
        if path.is_file()
    }


@intent("INT-GATE-001")
def test_failed_app_onboarding_rolls_back_byte_identical(
    failing_client: TestClient, platform_root: Path, fake_git: FakeGitPr
) -> None:
    """INT-GATE-001: a gate-failing onboarding restores every byte and ships nothing."""
    before = _snapshot(platform_root)
    res = failing_client.post(
        "/api/onboard/app",
        json={
            "name": "gamma-app",
            "display_name": "Gamma App",
            "description": "The gamma application",
            "icon": "mdi-gamma",
            "expose_mcp": True,
        },
    )
    assert res.status_code == 422
    body = res.json()
    assert body["error"] == "ValidationFailedError"
    assert body["new_failures"] == ["install/parity::manifest-teams-bijection"]
    assert body["report"]["failed"] == 1
    assert _snapshot(platform_root) == before
    assert not (platform_root / "teams" / "gamma-app").exists()
    assert fake_git.finalized == []
    assert fake_git.aborted == ["onboard/gamma-app"]


@intent("INT-GATE-001")
def test_failed_database_onboarding_restores_the_team_folder(
    failing_client: TestClient, platform_root: Path, fake_git: FakeGitPr
) -> None:
    before = _snapshot(platform_root)
    res = failing_client.post("/api/onboard/database", json={"name": "alpha-app"})
    assert res.status_code == 422
    assert _snapshot(platform_root) == before
    assert not (platform_root / "teams" / "alpha-app" / "jobs.yaml").exists()
    assert fake_git.finalized == []
    assert fake_git.aborted == ["onboard/alpha-app-db"]


@intent("INT-GATE-001")
def test_failed_identity_onboarding_restores_the_team_folder(
    failing_client: TestClient, platform_root: Path, fake_git: FakeGitPr
) -> None:
    before = _snapshot(platform_root)
    res = failing_client.post("/api/onboard/identity", json={"name": "alpha-app"})
    assert res.status_code == 422
    assert _snapshot(platform_root) == before
    assert not (platform_root / "teams" / "alpha-app" / "config.yaml").exists()
    assert fake_git.finalized == []
    assert fake_git.aborted == ["onboard/alpha-app-identity"]


@intent("INT-GATE-004")
def test_a_raising_pr_body_rolls_back_byte_identical(
    platform_root: Path, fake_git: FakeGitPr
) -> None:
    """INT-GATE-004: the pull-request body is composed between the gate and
    the publish, and a body that raises takes the publish rollback. Until the
    composition sat inside it, onboard_events called advisory_section with one
    argument, passed its gate, raised at the body, and left the grant's files
    written and onboard/<app> checked out for the next act to trip on (#24)."""
    container = build_container(platform_root, StubConformance(), fake_git)
    gated = container._gated_change()
    before = _snapshot(platform_root)

    def mutate() -> None:
        folder = platform_root / "teams" / "alpha-app"
        (folder / "jobs.yaml").write_text("kind: Job\n", encoding="utf-8")

    def body(*_args: object) -> str:
        raise TypeError("advisory_section() missing 1 required positional argument")

    with pytest.raises(TypeError):
        gated.execute(
            app="alpha-app",
            branch="onboard/alpha-app-events",
            touched_paths=("teams/alpha-app/jobs.yaml",),
            mutate=mutate,
            commit_message="feat(events): grant alpha-app bus access",
            pr_title="feat(events): grant alpha-app bus access",
            pr_body=body,
        )
    assert _snapshot(platform_root) == before
    assert fake_git.finalized == []
    assert fake_git.aborted == ["onboard/alpha-app-events"]


@intent("INT-GATE-004")
def test_failed_publishing_rolls_back_byte_identical(
    platform_root: Path, fake_git: FakeGitPr
) -> None:
    """INT-GATE-004: a passed gate does not make publishing succeed. When the
    pull request cannot be opened, the change rolls back exactly as a rejected
    one does, so a change that could never be offered leaves nothing behind."""
    fake_git.finalize_error = PrFailedError(
        "GitHub API POST /repos/o/r/pulls answered 502: bad gateway"
    )
    container = build_container(platform_root, StubConformance(), fake_git)
    client = TestClient(create_app(container))
    before = _snapshot(platform_root)
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
    assert res.status_code == 502
    assert res.json()["error"] == "PrFailedError"
    assert _snapshot(platform_root) == before
    assert not (platform_root / "teams" / "gamma-app").exists()
    assert fake_git.aborted == ["onboard/gamma-app"]


def test_pre_existing_failures_do_not_block_onboarding(
    platform_root: Path, fake_git: FakeGitPr
) -> None:
    """The gate is a baseline diff: the deploy branch's own failures are not
    the onboarding branch's fault."""
    from fastapi.testclient import TestClient

    from studio.adapters.inbound.http.app import create_app
    from tests.conftest import StubConformance, build_container, failing_report

    conformance = StubConformance([failing_report(), failing_report()])
    container = build_container(platform_root, conformance, fake_git)
    client = TestClient(create_app(container))
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
    assert res.status_code == 200, res.text
    assert fake_git.finalized[0]["branch"] == "onboard/gamma-app"


def test_pr_body_carries_the_gate_evidence(
    client: TestClient, fake_git: FakeGitPr
) -> None:
    client.post(
        "/api/onboard/app",
        json={
            "name": "gamma-app",
            "display_name": "Gamma App",
            "description": "The gamma application",
            "icon": "mdi-gamma",
            "expose_mcp": True,
        },
    )
    body = fake_git.finalized[0]["pr_body"]
    assert "### Conformance" in body
    assert "| passed | 3 | 3 |" in body
    assert "deploy branch (baseline)" in body
    assert "### Files" in body
    assert "`foundry.yaml`" in body
    assert "`teams/gamma-app/gateway.yaml`" in body
    assert "### Onboarding checklist" in body
    assert "gamma-app.lab.example.dev" in body
    assert "https://gamma-app.lab.example.dev/mcp" in body


@intent("INT-DELIVERY-001")
def test_pr_body_names_the_unverified_delivery_rows(
    platform_root: Path, fake_git: FakeGitPr
) -> None:
    """INT-DELIVERY-001: a delivery row whose team-owned leg could not be read
    reports skipped, and the PR the waiver admits names it as pending
    verification instead of letting it blend into the green count."""
    from fastapi.testclient import TestClient

    from studio.adapters.inbound.http.app import create_app
    from studio.domain.model.test_outcome import TestOutcome
    from tests.conftest import StubConformance, build_container, make_report

    report = make_report(
        ("install/parity::manifest-teams-bijection", TestOutcome.PASSED),
        ("install/delivery::argocd-application[gamma-app]", TestOutcome.PASSED),
        ("install/delivery::ci-caller[gamma-app]", TestOutcome.PASSED),
        ("install/delivery::deploy-branch[gamma-app]", TestOutcome.SKIPPED),
    )
    container = build_container(platform_root, StubConformance([report]), fake_git)
    client = TestClient(create_app(container))
    res = client.post(
        "/api/onboard/app",
        json={
            "name": "gamma-app",
            "display_name": "Gamma App",
            "description": "The gamma application",
            "icon": "mdi-gamma",
            "expose_mcp": False,
            "allow_bootstrap": True,
        },
    )
    assert res.status_code == 200, res.text
    body = fake_git.finalized[0]["pr_body"]
    assert "### Delivery pipeline" in body
    assert "`install/delivery::ci-caller[gamma-app]` passed" in body
    assert "`install/delivery::deploy-branch[gamma-app]` skipped" in body
    assert "A skipped row is a named warning, not a pass" in body


def _skipped_legs_report() -> ConformanceReport:
    from studio.domain.model.test_outcome import TestOutcome
    from tests.conftest import make_report

    return make_report(
        ("install/parity::manifest-teams-bijection", TestOutcome.PASSED),
        ("install/delivery::argocd-application[gamma-app]", TestOutcome.PASSED),
        ("install/delivery::ci-caller[gamma-app]", TestOutcome.SKIPPED),
        ("install/delivery::deploy-branch[gamma-app]", TestOutcome.SKIPPED),
        ("install/promotion::image-updater-promotes[gamma-app]", TestOutcome.SKIPPED),
        ("install/promotion::image-updater-released-set[gamma-app]", TestOutcome.SKIPPED),
    )


@intent("INT-DELIVERY-001")
def test_skipped_app_side_legs_refuse_the_onboarding_by_default(
    platform_root: Path, fake_git: FakeGitPr
) -> None:
    """INT-DELIVERY-001: an app whose app-side legs cannot be read is refused
    by default, rolled back byte-identical, with every skipped leg named and
    the waiver named, so the artifacts-first ordering is forced rather than
    shipping an app whose team side is entirely unverified."""
    from fastapi.testclient import TestClient

    from studio.adapters.inbound.http.app import create_app
    from tests.conftest import StubConformance, build_container

    before = _snapshot(platform_root)
    container = build_container(
        platform_root, StubConformance([_skipped_legs_report()]), fake_git
    )
    client = TestClient(create_app(container))
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
    assert res.status_code == 422, res.text
    body = res.json()
    assert body["error"] == "UnverifiedLegsError"
    assert body["skipped_legs"] == [
        "install/delivery::ci-caller[gamma-app]",
        "install/delivery::deploy-branch[gamma-app]",
        "install/promotion::image-updater-promotes[gamma-app]",
        "install/promotion::image-updater-released-set[gamma-app]",
    ]
    # The refusal names each leg, what makes it readable, and the waiver.
    assert "install/delivery::ci-caller[gamma-app]" in body["detail"]
    assert "install/delivery::deploy-branch[gamma-app]" in body["detail"]
    assert "install/promotion::image-updater-promotes[gamma-app]" in body["detail"]
    assert "install/promotion::image-updater-released-set[gamma-app]" in body["detail"]
    assert "build.yml" in body["detail"]
    assert "deploy-<install> branch" in body["detail"]
    assert "Image Updater bindings" in body["detail"]
    assert "devops/docker-compose.yml" in body["detail"]
    assert "allow_bootstrap" in body["detail"]
    assert body["report"]["skipped"] == 4
    # Rolled back byte-identical: nothing shipped, nothing left behind.
    assert _snapshot(platform_root) == before
    assert not (platform_root / "teams" / "gamma-app").exists()
    assert fake_git.finalized == []
    assert fake_git.aborted == ["onboard/gamma-app"]


@intent("INT-DELIVERY-001")
def test_bootstrap_waiver_admits_and_records_in_the_pr_body(
    platform_root: Path, fake_git: FakeGitPr
) -> None:
    """INT-DELIVERY-001: allow_bootstrap admits the skipped app-side legs (the
    deliberate walking-skeleton bootstrap) and the PR body records the waiver
    so the trail shows the skips were admitted on purpose."""
    from fastapi.testclient import TestClient

    from studio.adapters.inbound.http.app import create_app
    from tests.conftest import StubConformance, build_container

    container = build_container(
        platform_root, StubConformance([_skipped_legs_report()]), fake_git
    )
    client = TestClient(create_app(container))
    res = client.post(
        "/api/onboard/app",
        json={
            "name": "gamma-app",
            "display_name": "Gamma App",
            "description": "The gamma application",
            "icon": "mdi-gamma",
            "expose_mcp": False,
            "allow_bootstrap": True,
        },
    )
    assert res.status_code == 200, res.text
    assert fake_git.finalized[0]["branch"] == "onboard/gamma-app"
    body = fake_git.finalized[0]["pr_body"]
    assert "### Bootstrap waiver" in body
    assert (
        "bootstrap waiver: app-side conformance legs skipped by explicit allow_bootstrap"
        in body
    )
    assert "- `install/delivery::ci-caller[gamma-app]` skipped" in body
    assert "- `install/delivery::deploy-branch[gamma-app]` skipped" in body
    assert "- `install/promotion::image-updater-promotes[gamma-app]` skipped" in body
    assert "- `install/promotion::image-updater-released-set[gamma-app]` skipped" in body


@intent("INT-DELIVERY-001")
def test_released_set_leg_alone_refuses_without_the_waiver(
    platform_root: Path, fake_git: FakeGitPr
) -> None:
    """INT-DELIVERY-001: the released-set row is an app-side leg in its own
    right: a candidate report whose only skip is that row (the repo readable
    but its devops/docker-compose.yml missing or unparseable) refuses the
    onboarding without the waiver, and the waiver section names it."""
    from fastapi.testclient import TestClient

    from studio.adapters.inbound.http.app import create_app
    from studio.domain.model.test_outcome import TestOutcome
    from tests.conftest import StubConformance, build_container, make_report

    report = make_report(
        ("install/parity::manifest-teams-bijection", TestOutcome.PASSED),
        ("install/delivery::argocd-application[gamma-app]", TestOutcome.PASSED),
        ("install/delivery::ci-caller[gamma-app]", TestOutcome.PASSED),
        ("install/delivery::deploy-branch[gamma-app]", TestOutcome.PASSED),
        ("install/promotion::image-updater-promotes[gamma-app]", TestOutcome.PASSED),
        ("install/promotion::image-updater-released-set[gamma-app]", TestOutcome.SKIPPED),
    )
    before = _snapshot(platform_root)
    container = build_container(platform_root, StubConformance([report]), fake_git)
    client = TestClient(create_app(container))
    payload = {
        "name": "gamma-app",
        "display_name": "Gamma App",
        "description": "The gamma application",
        "icon": "mdi-gamma",
        "expose_mcp": False,
    }
    refused = client.post("/api/onboard/app", json=payload)
    assert refused.status_code == 422, refused.text
    body = refused.json()
    assert body["error"] == "UnverifiedLegsError"
    assert body["skipped_legs"] == [
        "install/promotion::image-updater-released-set[gamma-app]"
    ]
    assert "devops/docker-compose.yml" in body["detail"]
    assert "allow_bootstrap" in body["detail"]
    assert _snapshot(platform_root) == before
    assert fake_git.finalized == []
    waived = client.post("/api/onboard/app", json={**payload, "allow_bootstrap": True})
    assert waived.status_code == 200, waived.text
    pr_body = fake_git.finalized[0]["pr_body"]
    assert "### Bootstrap waiver" in pr_body
    assert "- `install/promotion::image-updater-released-set[gamma-app]` skipped" in pr_body


@intent("INT-DELIVERY-001")
def test_strict_admission_holds_for_the_capability_grants(
    platform_root: Path, fake_git: FakeGitPr
) -> None:
    """INT-DELIVERY-001: the database and identity grants ride the same gated
    change, so an app with unverified app-side legs refuses those too until
    the artifacts are readable or the waiver is explicit."""
    from fastapi.testclient import TestClient

    from studio.adapters.inbound.http.app import create_app
    from studio.domain.model.test_outcome import TestOutcome
    from tests.conftest import StubConformance, build_container, make_report

    report = make_report(
        ("install/parity::manifest-teams-bijection", TestOutcome.PASSED),
        ("install/delivery::ci-caller[alpha-app]", TestOutcome.SKIPPED),
    )
    container = build_container(platform_root, StubConformance([report]), fake_git)
    client = TestClient(create_app(container))
    refused = client.post("/api/onboard/database", json={"name": "alpha-app"})
    assert refused.status_code == 422
    assert refused.json()["error"] == "UnverifiedLegsError"
    assert not (platform_root / "teams" / "alpha-app" / "jobs.yaml").exists()
    waived = client.post(
        "/api/onboard/database", json={"name": "alpha-app", "allow_bootstrap": True}
    )
    assert waived.status_code == 200, waived.text
    assert "### Bootstrap waiver" in fake_git.finalized[0]["pr_body"]


@intent("INT-GRANT-004")
def test_advisory_credential_row_reports_without_refusing_the_change(
    platform_root: Path, fake_git: FakeGitPr
) -> None:
    """INT-GRANT-004: a candidate whose only new failure is the credential
    demand-grant row still ships, and the PR body names it.

    Refusing here would deadlock the ordering: the grant the row asks for is
    rendered into teams/<app>/, which this very onboarding creates, while the
    grant's own onboarding refuses an app the manifest does not yet carry. So
    the gate reports it and admits, and the warning rides the pull request.
    """
    conformance = StubConformance(
        [
            make_report(("install/parity::manifest-teams-bijection", TestOutcome.PASSED)),
            make_report(
                ("install/parity::manifest-teams-bijection", TestOutcome.PASSED),
                ("install/credentials::demand-grant[gamma-app]", TestOutcome.FAILED),
                exit_code=1,
            ),
        ]
    )
    container = build_container(platform_root, conformance, fake_git)
    client = TestClient(create_app(container))
    res = client.post(
        "/api/onboard/app",
        json={
            "name": "gamma-app",
            "display_name": "Gamma App",
            "description": "The gamma application",
            "icon": "mdi-gamma",
            "expose_mcp": False,
            "allow_bootstrap": True,
        },
    )
    assert res.status_code == 200
    assert fake_git.aborted == []
    assert len(fake_git.finalized) == 1
    body = fake_git.finalized[0]["pr_body"]
    assert "### Advisory" in body
    assert "install/credentials::demand-grant[gamma-app]" in body
    assert "foundry-onboard-keycloak" in body


@intent("INT-GATE-001")
def test_a_real_new_failure_beside_an_advisory_row_still_refuses(
    platform_root: Path, fake_git: FakeGitPr
) -> None:
    """INT-GATE-001: the advisory exemption is scoped to its own row; a
    genuine new failure alongside it rolls the change back as ever."""
    conformance = StubConformance(
        [
            make_report(("install/parity::manifest-teams-bijection", TestOutcome.PASSED)),
            make_report(
                ("install/parity::manifest-teams-bijection", TestOutcome.FAILED),
                ("install/credentials::demand-grant[gamma-app]", TestOutcome.FAILED),
                exit_code=1,
            ),
        ]
    )
    container = build_container(platform_root, conformance, fake_git)
    client = TestClient(create_app(container))
    res = client.post(
        "/api/onboard/app",
        json={
            "name": "gamma-app",
            "display_name": "Gamma App",
            "description": "The gamma application",
            "icon": "mdi-gamma",
            "expose_mcp": False,
            "allow_bootstrap": True,
        },
    )
    assert res.status_code == 422
    assert res.json()["new_failures"] == ["install/parity::manifest-teams-bijection"]
    assert fake_git.finalized == []
    assert not (platform_root / "teams" / "gamma-app").exists()
