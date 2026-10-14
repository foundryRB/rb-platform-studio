"""GetAppStatus tests: the evidence chain read link by link with mocked ports.

The tool exists so a delivery run polls one typed surface instead of
improvising six checks; these tests pin each link's ok/failed/skipped
semantics, the stage derivation, and the never-crash degradation on
half-onboarded apps and unreachable hosts.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pytest_intent import intent

from studio.adapters.outbound.platform_fs.fs_platform_repository import FsPlatformRepository
from studio.application.use_cases.get_app_status import GetAppStatus
from studio.domain.exceptions.entity_not_found_error import EntityNotFoundError
from studio.domain.model.app_status import AppStatus
from studio.domain.model.commit_info import CommitInfo
from studio.domain.model.delivery_stage import DeliveryStage
from studio.domain.model.link_status import LinkStatus
from studio.domain.model.pr_info import PrInfo
from studio.domain.model.probe_result import ProbeResult
from studio.domain.model.status_link import StatusLink
from studio.domain.model.test_outcome import TestOutcome
from studio.domain.model.workflow_run import WorkflowRun
from tests.conftest import FakeGitPr, FakeProbe, StubConformance, make_report


class FakeAppSource:
    """Canned AppRepoSource: every read answers None unless armed."""

    def __init__(
        self,
        *,
        default: str | None = None,
        run: WorkflowRun | None = None,
        files: dict[str, dict] | None = None,
        commit: CommitInfo | None = None,
    ) -> None:
        self.default = default
        self.run = run
        self.files = files or {}
        self.commit = commit

    def deploy_values(self, *, repo_url: str, branch: str, path: str) -> dict | None:
        return self.files.get(path)

    def branch_head(self, *, repo_url: str, branch: str) -> str | None:
        return "head"

    def default_branch(self, *, repo_url: str) -> str | None:
        return self.default

    def file_text(self, *, repo_url: str, branch: str, path: str) -> str | None:
        return None

    def branch_paths(self, *, repo_url: str, branch: str) -> frozenset[str] | None:
        return None

    def latest_workflow_run(self, *, repo_url: str, branch: str) -> WorkflowRun | None:
        return self.run

    def latest_commit(self, *, repo_url: str, branch: str, path: str) -> CommitInfo | None:
        return self.commit


class RaisingAppSource(FakeAppSource):
    """AppRepoSource whose repo-host reads blow up (the API erroring hard)."""

    def default_branch(self, *, repo_url: str) -> str | None:
        raise RuntimeError("GitHub API answered 500")


class FakeCluster:
    def __init__(
        self,
        state: str = "Synced",
        phase: str = "Succeeded",
        *,
        waiting: str = "",
        available: bool = True,
        revision: str = "head",
    ) -> None:
        self.state, self.phase, self.waiting, self.available = state, phase, waiting, available
        self.revision = revision

    def application(self, *, namespace: str, name: str) -> dict | None:
        if not self.available:
            return None
        return {
            "status": {
                "sync": {"status": self.state, "revision": self.revision},
                "operationState": {"phase": self.phase, "message": "observed"},
            }
        }

    def pods(self, *, namespace: str) -> tuple[dict, ...] | None:
        if not self.available:
            return None
        return (
            {
                "metadata": {"name": "app-pod"},
                "status": {
                    "phase": "Running",
                    "conditions": [
                        {"type": "Ready", "status": "False" if self.waiting else "True"}
                    ],
                    "containerStatuses": [
                        {
                            "name": "app",
                            "ready": not self.waiting,
                            "restartCount": 7,
                            "lastState": {"terminated": {"exitCode": 3}},
                            "state": {"waiting": {"reason": self.waiting}} if self.waiting else {},
                        }
                    ],
                },
            },
        )


class FakeCharts:
    def __init__(self, verdict: LinkStatus = LinkStatus.OK) -> None:
        self.verdict = verdict

    def compare(self, **kwargs: object) -> StatusLink:
        return StatusLink(self.verdict, "observed render comparison")


def _armed_source(app: str) -> FakeAppSource:
    """A source reading a healthy deploy branch: pinned chart, promoted tag,
    write-back commit, and a green CI run."""
    return FakeAppSource(
        default="main",
        run=WorkflowRun(
            name="Build",
            conclusion="success",
            url="https://github.example/runs/1",
            completed_at="2026-07-20T11:58:00Z",
        ),
        files={
            "prod/Chart.yaml": {
                "apiVersion": "v2",
                "name": app,
                "version": "1.4.0",
                "dependencies": [{"name": app, "version": "1.4.0"}],
            },
            "prod/values.yaml": {
                app: {"image": {"tag": "1.4.0", "repository": f"ghcr.io/test-org/{app}"}}
            },
        },
        commit=CommitInfo(
            sha="abc123def4567890abc123def4567890abc123de",
            message=f"build: promote {app} 1.4.0",
            committed_at="2026-07-20T12:00:00Z",
        ),
    )


def _app_side_report(
    app: str = "alpha-app", outcome: TestOutcome = TestOutcome.PASSED
) -> StubConformance:
    return StubConformance(
        [
            make_report(
                (f"install/delivery::ci-caller[{app}]", outcome),
                (f"install/delivery::deploy-branch[{app}]", outcome),
                (f"install/promotion::image-updater-promotes[{app}]", outcome),
                (f"install/credentials::demand-grant[{app}]", outcome),
            )
        ]
    )


def _status(
    platform_root: Path,
    *,
    name: str = "alpha-app",
    conformance: StubConformance | None = None,
    git: FakeGitPr | None = None,
    probe: FakeProbe | None = None,
    source: FakeAppSource | None = None,
    cluster: FakeCluster | None = None,
    charts: FakeCharts | None = None,
) -> AppStatus:
    use_case = GetAppStatus(
        repository=FsPlatformRepository(platform_root),
        conformance=conformance or _app_side_report(name),
        git=git or FakeGitPr(),
        probe=probe or FakeProbe(),
        app_repo=source,
        cluster=cluster or FakeCluster(),
        charts=charts or FakeCharts(),
    )
    return use_case.execute(name=name)


@pytest.mark.parametrize(
    ("state", "phase", "verdict"),
    [
        ("Synced", "Succeeded", LinkStatus.OK),
        ("OutOfSync", "Running", LinkStatus.PENDING),
        ("Unknown", "", LinkStatus.SKIPPED),
        ("Synced", "Failed", LinkStatus.FAILED),
        ("OutOfSync", "Error", LinkStatus.FAILED),
    ],
)
def test_sync_primary_evidence_gates_serving(
    platform_root: Path,
    state: str,
    phase: str,
    verdict: LinkStatus,
) -> None:
    status = _status(
        platform_root, source=_armed_source("alpha-app"), cluster=FakeCluster(state, phase)
    )
    assert status.sync.status is verdict
    assert "head" in status.sync.detail
    assert status.promotion.status is LinkStatus.OK
    assert (status.stage is DeliveryStage.SERVING) == (verdict is LinkStatus.OK)


def test_workload_failure_names_phenomenon_preserving_edge(platform_root: Path) -> None:
    status = _status(
        platform_root,
        source=_armed_source("alpha-app"),
        cluster=FakeCluster(waiting="CrashLoopBackOff"),
    )
    assert status.probe.status is LinkStatus.FAILED
    assert all(
        fact in status.probe.detail for fact in ("200", "CrashLoopBackOff", "exit 3", "restarts 7")
    )
    assert status.stage is DeliveryStage.PROMOTED


def test_synced_old_revision_cannot_verify_requested_head(platform_root: Path) -> None:
    status = _status(
        platform_root, source=_armed_source("alpha-app"), cluster=FakeCluster(revision="old-head")
    )
    assert status.sync.status is LinkStatus.SKIPPED
    assert "old-head" in status.sync.detail and "requested revision head" in status.sync.detail
    assert status.stage is DeliveryStage.PROMOTED


def test_pending_workload_cannot_earn_serving(platform_root: Path) -> None:
    status = _status(
        platform_root,
        source=_armed_source("alpha-app"),
        cluster=FakeCluster(waiting="ContainerCreating"),
    )
    assert status.probe.status is LinkStatus.PENDING
    assert status.stage is DeliveryStage.PROMOTED


@pytest.mark.parametrize("verdict", [LinkStatus.PENDING, LinkStatus.SKIPPED])
def test_chart_comparison_is_advisory_preserving_proven_serving(
    platform_root: Path,
    verdict: LinkStatus,
) -> None:
    status = _status(platform_root, source=_armed_source("alpha-app"), charts=FakeCharts(verdict))
    assert status.chart.status is verdict
    assert status.promotion.status is LinkStatus.OK
    assert status.stage is DeliveryStage.SERVING


def test_unavailable_cluster_is_unknown_with_edge_evidence(platform_root: Path) -> None:
    status = _status(
        platform_root, source=_armed_source("alpha-app"), cluster=FakeCluster(available=False)
    )
    assert status.sync.status is LinkStatus.SKIPPED
    assert status.probe.status is LinkStatus.SKIPPED
    assert "200" in status.probe.detail
    assert status.stage is DeliveryStage.PROMOTED


def _declare_ghost(platform_root: Path) -> None:
    """A manifest entry with no teams folder: the half-onboarded state."""
    manifest = platform_root / "foundry.yaml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8")
        + "- name: ghost-app\n  display: Ghost\n  icon: mdi-ghost\n",
        encoding="utf-8",
    )


class TestFullChain:
    @intent("INT-STATUS-001")
    def test_healthy_chain_reads_every_link_ok_and_stage_serving(self, platform_root: Path) -> None:
        """INT-STATUS-001: with every leg readable and green - app-side rows
        passed, CI success, the deploy branch pinned and promoted, the
        hostname answering 200 - every link reads ok and the stage earns
        serving."""
        probe = FakeProbe(
            by_url={
                "smoke/alpha-app.json": ProbeResult(
                    status_code=200,
                    latency_ms=8,
                    headers=(),
                    body='{"status":"passed","tag":"1.4.0","target":"https://alpha-app.lab.example.dev","total":6,"failed":0,"finished_at":"2026-07-20T12:05:00Z"}',
                )
            }
        )
        status = _status(platform_root, probe=probe, source=_armed_source("alpha-app"))
        assert status.stage is DeliveryStage.SERVING
        assert status.summary == "stage serving: every link ok"
        for _, link in status.links():
            assert link.status is LinkStatus.OK
        assert "alpha-app.lab.example.dev" in status.onboarded.detail
        assert status.onboarding_pr.detail == "none open"
        assert "install/delivery::ci-caller[alpha-app]=passed" in status.app_repo.detail
        assert "success" in status.ci.detail
        assert "artifacts-published proxy" in status.ci.detail
        assert "chart pinned 1.4.0" in status.promotion.detail
        assert "alpha-app.image.tag=1.4.0" in status.promotion.detail
        assert "abc123def456" in status.promotion.detail
        assert "2026-07-20T12:00:00Z" in status.promotion.detail
        assert "HTTP 200" in status.probe.detail
        assert "server=test-edge" in status.probe.detail
        assert "smoke passed on tag 1.4.0 - the promoted tag" in status.smoke.detail
        # Root for the serving signature, health for the build stamp, then the
        # smoke reporter for the deployed verdict.
        assert probe.urls == [
            "https://alpha-app.lab.example.dev/",
            "https://alpha-app.lab.example.dev/api/health",
            "https://docs.lab.example.dev/smoke/alpha-app.json",
        ]

    @intent("INT-STATUS-001")
    def test_half_onboarded_app_degrades_every_link_without_raising(
        self, platform_root: Path
    ) -> None:
        """INT-STATUS-001: a manifest entry with no teams folder answers a
        full chain - onboarded failed, the unreadable legs skipped with
        reasons - and never a crash."""
        _declare_ghost(platform_root)
        status = _status(
            platform_root,
            name="ghost-app",
            conformance=StubConformance(),
            source=_armed_source("ghost-app"),
        )
        assert status.stage is DeliveryStage.NOT_ONBOARDED
        assert status.onboarded.status is LinkStatus.FAILED
        assert "teams/ghost-app/ is missing" in status.onboarded.detail
        assert status.app_repo.status is LinkStatus.SKIPPED
        assert "no app-side conformance rows" in status.app_repo.detail
        # The skip names its construction: these legs are evaluated on the
        # gated onboarding's candidate state, so a caller never misreads a
        # baseline skip as a gap in the app's own artifacts.
        assert "candidate state" in status.app_repo.detail
        assert "not a gap in the app's own artifacts" in status.app_repo.detail
        assert status.ci.status is LinkStatus.SKIPPED
        assert "app repo unknown" in status.ci.detail
        assert status.promotion.status is LinkStatus.SKIPPED
        assert "nothing names the deploy branch" in status.promotion.detail
        assert "first non-ok link onboarded (failed)" in status.summary

    def test_unknown_app_raises_the_not_found_error(self, platform_root: Path) -> None:
        with pytest.raises(EntityNotFoundError):
            _status(platform_root, name="no-such-app")


class TestServedRelease:
    """The probe reads the running build off the health route the OIDC gate skips,
    so 'serving' names WHICH release answers - not merely that something does."""

    @staticmethod
    def _health(payload: str) -> ProbeResult:
        return ProbeResult(status_code=200, latency_ms=8, headers=(), body=payload)

    def test_served_version_matching_the_promoted_tag_is_named(self, platform_root: Path) -> None:
        probe = FakeProbe(
            ProbeResult(
                status_code=302,
                latency_ms=40,
                headers=(("server", "edge"),),
            ),
            by_url={"/api/health": self._health('{"status": "ok", "version": "1.4.0"}')},
        )
        status = _status(
            platform_root,
            name="beta-app",
            conformance=_app_side_report("beta-app"),
            probe=probe,
            source=_armed_source("beta-app"),
        )
        assert status.probe.status is LinkStatus.OK
        assert "running 1.4.0 - the promoted tag" in status.probe.detail

    def test_a_stale_pod_reports_both_versions_without_failing(self, platform_root: Path) -> None:
        """Promotion writes the tag back before the new pod is ready, so a
        disagreement is the normal state mid-rollout: it is reported, never
        failed, or every deploy would flap."""
        probe = FakeProbe(
            ProbeResult(status_code=302, latency_ms=40, headers=(("server", "edge"),)),
            by_url={"/api/health": self._health('{"status": "ok", "version": "1.3.9"}')},
        )
        status = _status(
            platform_root,
            name="beta-app",
            conformance=_app_side_report("beta-app"),
            probe=probe,
            source=_armed_source("beta-app"),
        )
        assert status.probe.status is LinkStatus.OK
        assert "running 1.3.9 while the promoted tag is 1.4.0" in status.probe.detail

    def test_an_app_that_has_not_adopted_the_skip_reads_exactly_as_before(
        self, platform_root: Path
    ) -> None:
        """The gate still swallows health on an app that predates the contract:
        the enrichment stays silent rather than inventing a failure."""
        probe = FakeProbe(
            ProbeResult(status_code=302, latency_ms=40, headers=(("server", "edge"),)),
            by_url={"/api/health": ProbeResult(status_code=302, latency_ms=6, headers=())},
        )
        status = _status(
            platform_root,
            name="beta-app",
            conformance=_app_side_report("beta-app"),
            probe=probe,
            source=_armed_source("beta-app"),
        )
        assert status.probe.status is LinkStatus.OK
        assert "serving behind its auth proxy" in status.probe.detail
        assert "running" not in status.probe.detail

    def test_a_health_route_without_a_build_stamp_stays_silent(self, platform_root: Path) -> None:
        probe = FakeProbe(
            ProbeResult(status_code=302, latency_ms=40, headers=(("server", "edge"),)),
            by_url={"/api/health": self._health('{"status": "ok"}')},
        )
        status = _status(
            platform_root,
            name="beta-app",
            conformance=_app_side_report("beta-app"),
            probe=probe,
            source=_armed_source("beta-app"),
        )
        assert status.probe.status is LinkStatus.OK
        assert "running" not in status.probe.detail

    def test_an_unreadable_health_body_never_breaks_the_status_read(
        self, platform_root: Path
    ) -> None:
        probe = FakeProbe(
            ProbeResult(status_code=302, latency_ms=40, headers=(("server", "edge"),)),
            by_url={"/api/health": self._health("<html>not json</html>")},
        )
        status = _status(
            platform_root,
            name="beta-app",
            conformance=_app_side_report("beta-app"),
            probe=probe,
            source=_armed_source("beta-app"),
        )
        assert status.probe.status is LinkStatus.OK
        assert "running" not in status.probe.detail


class TestProbeLink:
    @intent("INT-STATUS-001")
    def test_probe_302_behind_a_granted_identity_reads_ok(self, platform_root: Path) -> None:
        """INT-STATUS-001: beta-app holds an identity grant, so a 302 at the
        edge is the auth proxy's expected signature and the probe reads ok;
        the identity caveat stays skipped, naming the unverified round-trip."""
        probe = FakeProbe(
            ProbeResult(
                status_code=302,
                latency_ms=40,
                headers=(("server", "edge"), ("location", "https://idp.example/auth")),
            ),
            by_url={
                # A passed smoke keeps the caveat the chain's one standing
                # non-ok: the summary below is exactly what this test pins.
                "smoke/beta-app.json": ProbeResult(
                    status_code=200,
                    latency_ms=8,
                    headers=(),
                    body='{"status":"passed","tag":"1.4.0","total":4,"failed":0}',
                )
            },
        )
        status = _status(
            platform_root,
            name="beta-app",
            conformance=_app_side_report("beta-app"),
            probe=probe,
            source=_armed_source("beta-app"),
        )
        assert status.probe.status is LinkStatus.OK
        assert "serving behind its auth proxy" in status.probe.detail
        assert "location=https://idp.example/auth" in status.probe.detail
        assert status.stage is DeliveryStage.SERVING
        assert status.identity_caveat.status is LinkStatus.SKIPPED
        assert "OIDC login round-trip unverified" in status.identity_caveat.detail
        assert "operator-verified" in status.identity_caveat.detail
        assert "first non-ok link identity_caveat (skipped)" in status.summary

    @intent("INT-STATUS-001")
    def test_probe_302_without_an_identity_grant_reads_failed(self, platform_root: Path) -> None:
        """INT-STATUS-001: alpha-app has no identity grant, so a 302 is not a
        serving signature and the probe fails rather than green-washing an
        unexpected redirect."""
        probe = FakeProbe(ProbeResult(status_code=302, latency_ms=40, headers=()))
        status = _status(platform_root, probe=probe, source=_armed_source("alpha-app"))
        assert status.probe.status is LinkStatus.FAILED
        assert "not a serving signature" in status.probe.detail

    @intent("INT-STATUS-001")
    def test_probe_401_without_a_grant_reads_ok_when_the_health_route_answers(
        self, platform_root: Path
    ) -> None:
        """INT-STATUS-001: alpha-app has no identity grant, so a 401 at the root
        is the app gating its own callers; a 200 from its health route proves it
        serves, and the one read of that route names the running build."""
        probe = FakeProbe(
            ProbeResult(status_code=401, latency_ms=40, headers=(("server", "uvicorn"),)),
            by_url={
                "/api/health": ProbeResult(
                    status_code=200,
                    latency_ms=8,
                    headers=(),
                    body='{"status": "ok", "version": "1.4.0"}',
                )
            },
        )
        status = _status(platform_root, probe=probe, source=_armed_source("alpha-app"))
        assert status.probe.status is LinkStatus.OK
        assert "serving behind the app's own auth" in status.probe.detail
        assert "running 1.4.0" in status.probe.detail
        assert status.stage is DeliveryStage.SERVING
        assert sum(url.endswith("/api/health") for url in probe.urls) == 1

    @intent("INT-STATUS-001")
    def test_probe_401_without_a_grant_reads_failed_when_the_health_route_refuses(
        self, platform_root: Path
    ) -> None:
        """INT-STATUS-001: a health route answering 401 as well proves no more
        than the root did, so the probe fails and the stage stays promoted."""
        probe = FakeProbe(
            ProbeResult(status_code=401, latency_ms=40, headers=()),
            by_url={"/api/health": ProbeResult(status_code=401, latency_ms=6, headers=())},
        )
        status = _status(platform_root, probe=probe, source=_armed_source("alpha-app"))
        assert status.probe.status is LinkStatus.FAILED
        assert "not a serving signature" in status.probe.detail
        assert status.stage is DeliveryStage.PROMOTED

    @intent("INT-STATUS-001")
    def test_probe_timeout_reads_failed_and_the_stage_stays_promoted(
        self, platform_root: Path
    ) -> None:
        """INT-STATUS-001: no response is a failed probe (never a crash), and
        with the promotion evidence in git the stage reads promoted, not
        serving."""
        probe = FakeProbe(
            ProbeResult(
                status_code=None,
                latency_ms=5000,
                headers=(),
                error="ConnectTimeout: timed out",
            )
        )
        status = _status(platform_root, probe=probe, source=_armed_source("alpha-app"))
        assert status.probe.status is LinkStatus.FAILED
        assert "no response" in status.probe.detail
        assert "ConnectTimeout" in status.probe.detail
        assert status.stage is DeliveryStage.PROMOTED

    @intent("INT-STATUS-001")
    def test_probe_follows_the_gateway_hostname_not_the_app_name(self, platform_root: Path) -> None:
        """INT-STATUS-001: the probe reads "the app hostname" off the Gateway
        listener, so an app serving on a short host is probed there.

        Deriving <name>.<zone> instead probes a name external-dns never
        published: the probe fails, and because serving requires it, the app
        reads promoted forever however healthy it is.
        """
        gateway = platform_root / "teams" / "alpha-app" / "gateway.yaml"
        gateway.write_text(
            gateway.read_text(encoding="utf-8").replace(
                "hostname: alpha-app.lab.example.dev", "hostname: a1.lab.example.dev"
            ),
            encoding="utf-8",
        )
        probe = FakeProbe()
        status = _status(platform_root, probe=probe, source=_armed_source("alpha-app"))
        assert probe.urls[0] == "https://a1.lab.example.dev/"
        assert "alpha-app.lab.example.dev" not in " ".join(probe.urls)
        assert status.probe.status is LinkStatus.OK
        assert "a1.lab.example.dev" in status.onboarded.detail

    def test_probe_unexpected_status_reads_failed(self, platform_root: Path) -> None:
        probe = FakeProbe(ProbeResult(status_code=503, latency_ms=30, headers=()))
        status = _status(platform_root, probe=probe, source=_armed_source("alpha-app"))
        assert status.probe.status is LinkStatus.FAILED
        assert "HTTP 503" in status.probe.detail


def _smoke_probe(result: ProbeResult) -> FakeProbe:
    """A probe whose smoke-reporter read answers ``result`` and whose app
    probes answer the healthy default."""
    return FakeProbe(by_url={"smoke/alpha-app.json": result})


class TestSmokeLink:
    @intent("INT-STATUS-002")
    def test_a_passed_verdict_reads_ok_naming_the_tested_tag(self, platform_root: Path) -> None:
        """INT-STATUS-002: a parsed passed result reads ok and names the
        tested tag beside the promoted one."""
        probe = _smoke_probe(
            ProbeResult(
                status_code=200,
                latency_ms=8,
                headers=(),
                body='{"status":"passed","tag":"1.4.0","target":"https://alpha-app.lab.example.dev","total":6,"failed":0,"finished_at":"2026-07-20T12:05:00Z"}',
            )
        )
        status = _status(platform_root, probe=probe, source=_armed_source("alpha-app"))
        assert status.smoke.status is LinkStatus.OK
        assert "smoke passed on tag 1.4.0 - the promoted tag" in status.smoke.detail
        assert "6 specs" in status.smoke.detail

    @intent("INT-STATUS-002")
    def test_a_stale_tag_reports_the_gap_without_failing(self, platform_root: Path) -> None:
        """INT-STATUS-002: a passed verdict for an older tag reports the
        promoted tag beside it rather than failing; promotion writes back
        before the smoke re-runs."""
        probe = _smoke_probe(
            ProbeResult(
                status_code=200,
                latency_ms=8,
                headers=(),
                body='{"status":"passed","tag":"1.3.0","total":6,"failed":0}',
            )
        )
        status = _status(platform_root, probe=probe, source=_armed_source("alpha-app"))
        assert status.smoke.status is LinkStatus.OK
        assert "tag 1.3.0" in status.smoke.detail
        assert "promoted tag is 1.4.0" in status.smoke.detail

    @intent("INT-STATUS-002")
    def test_a_failed_verdict_reads_failed_with_the_counts(self, platform_root: Path) -> None:
        """INT-STATUS-002: status failed reads failed carrying the counts the
        result publishes."""
        probe = _smoke_probe(
            ProbeResult(
                status_code=200,
                latency_ms=8,
                headers=(),
                body='{"status":"failed","tag":"1.4.0","total":6,"failed":2,"finished_at":"2026-07-20T12:05:00Z"}',
            )
        )
        status = _status(platform_root, probe=probe, source=_armed_source("alpha-app"))
        assert status.smoke.status is LinkStatus.FAILED
        assert "2 of 6 specs failed" in status.smoke.detail

    @intent("INT-STATUS-002")
    def test_no_published_result_reads_skipped_naming_the_contract(
        self, platform_root: Path
    ) -> None:
        """INT-STATUS-002: a 404 is an app that has not adopted the optional
        contract - skipped, never failed."""
        probe = _smoke_probe(ProbeResult(status_code=404, latency_ms=8, headers=()))
        status = _status(platform_root, probe=probe, source=_armed_source("alpha-app"))
        assert status.smoke.status is LinkStatus.SKIPPED
        assert "optional" in status.smoke.detail

    @intent("INT-STATUS-002")
    def test_a_dark_reporter_reads_skipped_never_app_evidence(self, platform_root: Path) -> None:
        """INT-STATUS-002: a reporter that does not answer proves nothing
        about the app; the link skips with the reason."""
        probe = _smoke_probe(
            ProbeResult(
                status_code=None,
                latency_ms=5000,
                headers=(),
                error="ConnectTimeout: timed out",
            )
        )
        status = _status(platform_root, probe=probe, source=_armed_source("alpha-app"))
        assert status.smoke.status is LinkStatus.SKIPPED
        assert "not an app failure" in status.smoke.detail
        # The app's own links keep their healthy reads: only the smoke skips.
        assert status.probe.status is LinkStatus.OK
        assert status.stage is DeliveryStage.SERVING

    @intent("INT-STATUS-002")
    def test_a_reporter_error_status_reads_skipped(self, platform_root: Path) -> None:
        """INT-STATUS-002: a 5xx from the reporter is platform trouble, not
        app evidence."""
        probe = _smoke_probe(ProbeResult(status_code=503, latency_ms=30, headers=()))
        status = _status(platform_root, probe=probe, source=_armed_source("alpha-app"))
        assert status.smoke.status is LinkStatus.SKIPPED
        assert "HTTP 503" in status.smoke.detail

    @intent("INT-STATUS-002")
    def test_an_unreadable_published_verdict_reads_failed(self, platform_root: Path) -> None:
        """INT-STATUS-002: a 200 that does not parse as the contract is a
        defect on the evidence surface, not an absence - failed, loudly."""
        probe = _smoke_probe(
            ProbeResult(status_code=200, latency_ms=8, headers=(), body="not json")
        )
        status = _status(platform_root, probe=probe, source=_armed_source("alpha-app"))
        assert status.smoke.status is LinkStatus.FAILED
        assert "must be readable" in status.smoke.detail

    @intent("INT-STATUS-002")
    def test_the_smoke_link_stays_outside_the_stage_derivation(self, platform_root: Path) -> None:
        """INT-STATUS-002: a failed smoke never demotes a serving stage."""
        probe = _smoke_probe(
            ProbeResult(
                status_code=200,
                latency_ms=8,
                headers=(),
                body='{"status":"failed","tag":"1.4.0","total":6,"failed":6}',
            )
        )
        status = _status(platform_root, probe=probe, source=_armed_source("alpha-app"))
        assert status.smoke.status is LinkStatus.FAILED
        assert status.stage is DeliveryStage.SERVING


class TestCiLink:
    @intent("INT-STATUS-001")
    def test_ci_api_error_reads_skipped_with_the_reason_never_a_crash(
        self, platform_root: Path
    ) -> None:
        """INT-STATUS-001: a repo host erroring hard degrades the CI link to
        skipped with the reason; the read itself completes."""
        status = _status(platform_root, source=RaisingAppSource())
        assert status.ci.status is LinkStatus.SKIPPED
        assert "CI runs unreadable off the repo host" in status.ci.detail
        assert "GitHub API answered 500" in status.ci.detail

    def test_ci_without_a_wired_source_reads_skipped(self, platform_root: Path) -> None:
        status = _status(platform_root, source=None)
        assert status.ci.status is LinkStatus.SKIPPED
        assert "no app-repo source wired" in status.ci.detail

    def test_ci_without_a_readable_run_reads_skipped(self, platform_root: Path) -> None:
        status = _status(platform_root, source=FakeAppSource(default="main"))
        assert status.ci.status is LinkStatus.SKIPPED
        assert "no completed workflow run readable" in status.ci.detail

    def test_ci_failure_conclusion_reads_failed(self, platform_root: Path) -> None:
        source = _armed_source("alpha-app")
        red = FakeAppSource(
            default="main",
            run=WorkflowRun(
                name="Build",
                conclusion="failure",
                url="https://github.example/runs/2",
                completed_at="2026-07-20T11:58:00Z",
            ),
            files=source.files,
            commit=source.commit,
        )
        status = _status(platform_root, source=red)
        assert status.ci.status is LinkStatus.FAILED
        assert "concluded failure" in status.ci.detail


class TestAppRepoLink:
    @intent("INT-STATUS-001")
    def test_skipped_app_side_legs_read_skipped_with_the_reason(self, platform_root: Path) -> None:
        """INT-STATUS-001: the app-side legs reuse the conformance rows, and
        a skipped row keeps the link skipped, never a pass."""
        status = _status(
            platform_root,
            conformance=_app_side_report("alpha-app", TestOutcome.SKIPPED),
            source=_armed_source("alpha-app"),
        )
        assert status.app_repo.status is LinkStatus.SKIPPED
        assert "install/delivery::ci-caller[alpha-app]=skipped" in status.app_repo.detail
        assert "never a pass" in status.app_repo.detail

    def test_failed_app_side_leg_reads_failed(self, platform_root: Path) -> None:
        status = _status(
            platform_root,
            conformance=_app_side_report("alpha-app", TestOutcome.FAILED),
            source=_armed_source("alpha-app"),
        )
        assert status.app_repo.status is LinkStatus.FAILED
        assert "install/delivery::deploy-branch[alpha-app]=failed" in status.app_repo.detail

    def test_broken_conformance_suite_reads_skipped(self, platform_root: Path) -> None:
        broken = StubConformance([make_report(exit_code=2, output="boom")])
        status = _status(platform_root, conformance=broken)
        assert status.app_repo.status is LinkStatus.SKIPPED
        assert "exit 2" in status.app_repo.detail


class TestPromotionLink:
    @intent("INT-STATUS-001")
    def test_unreadable_deploy_branch_reads_skipped(self, platform_root: Path) -> None:
        """INT-STATUS-001: a deploy branch not stood up yet keeps the
        promotion link skipped with the reason, never guessed."""
        status = _status(platform_root, source=FakeAppSource(default="main"))
        assert status.promotion.status is LinkStatus.SKIPPED
        assert "unreadable on deploy-test" in status.promotion.detail
        assert status.stage is DeliveryStage.AWAITING_FIRST_ARTIFACTS

    def test_mismatched_bindings_read_failed(self, platform_root: Path) -> None:
        """Values releasing under images.<comp> while the binding writes
        image.tag is the silent never-promotes state: the link fails."""
        source = _armed_source("alpha-app")
        source.files["prod/values.yaml"] = {"alpha-app": {"images": {"server": {"tag": "2.0.0"}}}}
        status = _status(platform_root, source=source)
        assert status.promotion.status is LinkStatus.FAILED
        assert "alpha-app.image.tag is not in the deploy values" in status.promotion.detail


class TestOnboardingPrLink:
    def test_open_onboarding_pr_is_reported_with_number_and_url(self, platform_root: Path) -> None:
        _declare_ghost(platform_root)
        git = FakeGitPr()
        git.open.append(
            PrInfo(
                number=9,
                title="feat(teams): onboard ghost-app",
                url="https://github.example/pr/9",
                branch="onboard/ghost-app",
                state="open",
                merged=False,
            )
        )
        status = _status(platform_root, name="ghost-app", conformance=StubConformance(), git=git)
        assert status.onboarding_pr.status is LinkStatus.OK
        assert "#9" in status.onboarding_pr.detail
        assert "https://github.example/pr/9" in status.onboarding_pr.detail
        assert status.stage is DeliveryStage.PR_OPEN

    def test_unreadable_prs_read_skipped_never_a_crash(self, platform_root: Path) -> None:
        class BrokenGit(FakeGitPr):
            def open_prs(self) -> tuple[PrInfo, ...]:
                raise RuntimeError("GitHub API unreachable")

        status = _status(platform_root, git=BrokenGit())
        assert status.onboarding_pr.status is LinkStatus.SKIPPED
        assert "GitHub API unreachable" in status.onboarding_pr.detail


class TestStageDerivation:
    @intent("INT-STATUS-001")
    @pytest.mark.parametrize(
        ("onboarded", "pr_open", "promotion_armed", "probe_code", "expected"),
        [
            (False, True, False, 200, DeliveryStage.PR_OPEN),
            (False, False, False, 200, DeliveryStage.NOT_ONBOARDED),
            (True, False, False, 200, DeliveryStage.AWAITING_FIRST_ARTIFACTS),
            (True, False, True, None, DeliveryStage.PROMOTED),
            (True, False, True, 503, DeliveryStage.PROMOTED),
            (True, False, True, 200, DeliveryStage.SERVING),
        ],
    )
    def test_stage_derivation_table(
        self,
        platform_root: Path,
        onboarded: bool,
        pr_open: bool,
        promotion_armed: bool,
        probe_code: int | None,
        expected: DeliveryStage,
    ) -> None:
        """INT-STATUS-001: the stage reads off the links exactly as the use
        case docstring derives it; serving requires promotion AND probe ok."""
        name = "alpha-app" if onboarded else "ghost-app"
        if not onboarded:
            _declare_ghost(platform_root)
        git = FakeGitPr()
        if pr_open:
            git.open.append(
                PrInfo(
                    number=9,
                    title="feat(teams): onboard ghost-app",
                    url="https://github.example/pr/9",
                    branch="onboard/ghost-app",
                    state="open",
                    merged=False,
                )
            )
        probe_result = (
            ProbeResult(status_code=probe_code, latency_ms=10, headers=())
            if probe_code is not None
            else ProbeResult(status_code=None, latency_ms=5000, headers=(), error="timeout")
        )
        status = _status(
            platform_root,
            name=name,
            conformance=_app_side_report(name),
            git=git,
            probe=FakeProbe(probe_result),
            source=_armed_source(name) if promotion_armed else None,
        )
        assert status.stage is expected


class TestRestSurface:
    def test_status_route_mirrors_the_chain(self, client: TestClient) -> None:
        res = client.get("/api/apps/alpha-app/status")
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["name"] == "alpha-app"
        assert body["stage"] == "awaiting_first_artifacts"
        for link in (
            "onboarded",
            "onboarding_pr",
            "app_repo",
            "ci",
            "promotion",
            "probe",
            "smoke",
            "identity_caveat",
        ):
            assert body[link]["status"] in {"ok", "failed", "skipped"}
            assert body[link]["detail"]
        assert body["onboarded"]["status"] == "ok"
        assert "alpha-app.lab.example.dev" in body["onboarded"]["detail"]
        assert body["probe"]["status"] == "skipped"
        assert "200" in body["probe"]["detail"]
        assert body["sync"]["status"] == "skipped"
        assert body["chart"]["status"] == "skipped"
        # No app-repo source is wired in the test composition: the skips name it.
        assert body["ci"]["status"] == "skipped"
        assert body["summary"].startswith("stage awaiting_first_artifacts")

    def test_unknown_app_status_is_404(self, client: TestClient) -> None:
        res = client.get("/api/apps/no-such-app/status")
        assert res.status_code == 404
        assert res.json()["error"] == "EntityNotFoundError"


class TestCredentialsLink:
    @intent("INT-GRANT-004")
    def test_ungranted_credential_reads_failed_and_leads_the_summary(
        self, platform_root: Path
    ) -> None:
        """INT-GRANT-004: a failing demand-grant row reads failed on its own
        link and, sitting before probe, becomes the summary's first non-ok
        link - so the chain names the cause instead of blaming the edge."""
        report = make_report(
            ("install/delivery::ci-caller[alpha-app]", TestOutcome.PASSED),
            ("install/credentials::demand-grant[alpha-app]", TestOutcome.FAILED),
            exit_code=1,
        )
        # The link carries the row's own finding: it names the kind and the
        # skill, which a fixed message could not once a third kind existed.
        finding = (
            "teams/alpha-app/ grants events and the chart names nats-alpha-app, "
            "but its block is enabled: false, so nothing consumes the grant"
        )
        report = replace(
            report,
            results=tuple(
                replace(r, detail=finding) if r.node_id.startswith("install/credentials") else r
                for r in report.results
            ),
        )
        conformance = StubConformance([report])
        status = _status(
            platform_root,
            conformance=conformance,
            source=_armed_source("alpha-app"),
            probe=FakeProbe(ProbeResult(status_code=503, headers=(), latency_ms=5)),
        )
        assert status.credentials.status is LinkStatus.FAILED
        assert "CreateContainerConfigError" in status.credentials.detail
        assert finding in status.credentials.detail
        assert "keycloak" not in status.credentials.detail
        assert status.summary == "stage promoted: first non-ok link credentials (failed)"

    @intent("INT-GRANT-004")
    def test_unreadable_chart_reads_skipped_never_ok(self, platform_root: Path) -> None:
        """INT-GRANT-004: an unreadable app chart degrades to skipped, which
        never reads as a verified grant."""
        conformance = StubConformance(
            [make_report(("install/credentials::demand-grant[alpha-app]", TestOutcome.SKIPPED))]
        )
        status = _status(platform_root, conformance=conformance)
        assert status.credentials.status is LinkStatus.SKIPPED
        assert "unreadable" in status.credentials.detail

    @intent("INT-GRANT-004")
    def test_app_with_no_credential_row_skips_rather_than_claiming_ok(
        self, platform_root: Path
    ) -> None:
        """INT-GRANT-004: rows exist only for apps the manifest and teams/
        already carry, so a not-yet-onboarded app has nothing to judge."""
        conformance = StubConformance([make_report(exit_code=0)])
        status = _status(platform_root, conformance=conformance)
        assert status.credentials.status is LinkStatus.SKIPPED
        assert "no credential row" in status.credentials.detail

    @intent("INT-GRANT-004")
    def test_granted_credential_reads_ok(self, platform_root: Path) -> None:
        conformance = StubConformance(
            [make_report(("install/credentials::demand-grant[alpha-app]", TestOutcome.PASSED))]
        )
        status = _status(platform_root, conformance=conformance)
        assert status.credentials.status is LinkStatus.OK
        assert "teams/alpha-app/" in status.credentials.detail


class TestGrantDriftLink:
    @intent("INT-GRANT-007")
    def test_a_template_faithful_grant_reads_ok(self, platform_root: Path) -> None:
        """beta-app's identity grant is rendered from the canonical template, so
        the link reports it in sync. The fixture renders rather than restates for
        exactly this reason: a hand-copied grant goes stale the moment the
        template moves, and then this link reports the fixture, not the app."""
        status = _status(platform_root, name="beta-app")
        assert status.grant_drift.status is LinkStatus.OK
        assert "matches the canonical template" in status.grant_drift.detail

    @intent("INT-GRANT-007")
    def test_a_hand_edited_grant_is_reported_without_refusing_anything(
        self, platform_root: Path
    ) -> None:
        """The defect this exists for: someone edits the branch by hand and no
        gate notices, because a frozen grant is not wrong against any other
        check. It is advisory - the link fails, the app is still readable."""
        config = platform_root / "teams" / "beta-app" / "config.yaml"
        config.write_text(
            config.read_text(encoding="utf-8").replace(
                "        redirectUris:\n",
                "        webOrigins:\n          - https://beta-app.lab.example.dev\n"
                "        redirectUris:\n",
                1,
            ),
            encoding="utf-8",
        )
        status = _status(platform_root, name="beta-app")
        assert status.grant_drift.status is LinkStatus.FAILED
        assert "config.yaml" in status.grant_drift.detail
        assert "no longer matches the canonical template" in status.grant_drift.detail
        # Advisory: every other link is still computed and the app still reads.
        assert status.app == "beta-app"
        assert status.onboarded.status is LinkStatus.OK

    @intent("INT-GRANT-007")
    def test_an_app_with_no_identity_grant_reads_ok_not_drifted(self, platform_root: Path) -> None:
        """alpha-app holds no realm; reporting that as a difference would make
        every app without a capability look broken."""
        status = _status(platform_root, name="alpha-app")
        assert status.grant_drift.status is LinkStatus.OK
        assert "no identity grant to compare" in status.grant_drift.detail

    @intent("INT-GRANT-007")
    def test_admitting_a_person_to_the_realm_does_not_read_as_drift(
        self, platform_root: Path
    ) -> None:
        """The realm's user list is its access allowlist, filled by hand. If
        admitting somebody read as drift, the link would be red for every realm
        anyone actually uses - and the obvious "fix" would delete the person."""
        config = platform_root / "teams" / "beta-app" / "config.yaml"
        config.write_text(
            config.read_text(encoding="utf-8").replace(
                "      - username: beta-app-admin\n",
                "      - username: someone\n"
                "        email: someone@example.test\n"
                "        enabled: true\n"
                "        emailVerified: true\n"
                "      - username: beta-app-admin\n",
                1,
            ),
            encoding="utf-8",
        )
        status = _status(platform_root, name="beta-app")
        assert status.grant_drift.status is LinkStatus.OK
        assert "matches the canonical template" in status.grant_drift.detail
