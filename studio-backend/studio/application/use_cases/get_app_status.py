"""Use case: read one app's delivery evidence chain as typed links."""

from __future__ import annotations

import json

from studio.application.ports.outbound.app_repo_source import AppRepoSource
from studio.application.ports.outbound.chart_reader import ChartReader
from studio.application.ports.outbound.cluster_reader import ClusterReader
from studio.application.ports.outbound.conformance_runner import ConformanceRunner
from studio.application.ports.outbound.git_pr import GitPr
from studio.application.ports.outbound.http_probe import HttpProbe
from studio.application.ports.outbound.platform_repository import PlatformRepository
from studio.domain.exceptions.entity_not_found_error import EntityNotFoundError
from studio.domain.exceptions.unverified_legs_error import APP_SIDE_LEGS
from studio.domain.model.app_status import AppStatus
from studio.domain.model.conformance_report import ConformanceReport
from studio.domain.model.delivery_stage import DeliveryStage
from studio.domain.model.link_status import LinkStatus
from studio.domain.model.pr_info import PrInfo
from studio.domain.model.probe_result import ProbeResult
from studio.domain.model.status_link import StatusLink
from studio.domain.model.team_manifest import TeamManifest
from studio.domain.model.test_outcome import TestOutcome
from studio.domain.services.change_branch import onboard_branch
from studio.domain.services.cluster_evidence import sync_evidence, workload_evidence
from studio.domain.services.credential_demand import DEMAND_GRANT_ROW, effective_values
from studio.domain.services.grant_drift import grant_drift
from studio.domain.services.identity_grant import render_identity_blocks
from studio.domain.services.image_promotion import (
    ANNOTATION_PREFIX,
    bound_tag_values,
    unpromoted_bindings,
)
from studio.domain.services.team_documents import GRANT_FILES
from studio.logging import get_logger

__all__ = ["GetAppStatus"]

logger = get_logger(__name__)

_IDENTITY_CAVEAT = (
    "OIDC login round-trip unverified: a 302/401 at the edge does not prove "
    "sign-in works; the realm callback registration with the shared IdP is "
    "operator-verified"
)


class GetAppStatus:
    """Implements AppStatusPort: one read assembling the whole evidence chain.

    The chain reads git, the repo host, published chart artifacts, the primary
    Kubernetes API, and the edge. Application sync and workload observations
    are scoped to explicit platform grants; unreadable facts stay unknown.

    Every link degrades to skipped or failed with a reason rather than
    raising, so a half-onboarded app still answers; only a name with no
    manifest entry, no teams folder, and no open onboarding PR is unknown.

    Stage derivation, from the links in order:

    - the onboarded link not ok with an open ``onboard/<name>`` PR:
      ``pr_open`` (admission prepared, the platform repo's CI has not merged
      it yet);
    - the onboarded link not ok otherwise: ``not_onboarded``;
    - onboarded ok but the promotion link not ok:
      ``awaiting_first_artifacts`` (nothing readable on the deploy branch's
      prod/ proves a release landed yet);
    - promotion ok but the probe link not ok: ``promoted`` (the release is
      visible in git, the hostname does not answer as serving);
    - promotion, sync AND probe ok: ``serving``, the only stage that claims
      live, and it requires both the git evidence and the hostname answering.

    The credentials link is read from the conformance report rather than
    derived here, and it is deliberately outside the stage derivation: it
    explains a hostname that does not answer without changing what the stages
    mean, so an app whose chart names an ungranted credential reads as
    ``promoted`` with credentials as its first non-ok link.
    """

    def __init__(
        self,
        repository: PlatformRepository,
        conformance: ConformanceRunner,
        git: GitPr,
        probe: HttpProbe,
        app_repo: AppRepoSource | None,
        cluster: ClusterReader | None = None,
        charts: ChartReader | None = None,
        kube_version: str = "1.31.0",
        api_versions: tuple[str, ...] = (),
    ) -> None:
        self._repository = repository
        self._conformance = conformance
        self._git = git
        self._probe = probe
        self._app_repo = app_repo
        self._cluster = cluster
        self._charts = charts
        self._kube_version = kube_version
        self._api_versions = api_versions

    def execute(self, *, name: str) -> AppStatus:
        declared = any(entry.name == name for entry in self._repository.manifest_entries())
        manifest = self._repository.team_manifest(name)
        open_pr, onboarding_pr = self._onboarding_pr(name)
        if not declared and manifest is None and open_pr is None:
            raise EntityNotFoundError("app", name)
        zone = self._repository.zone()
        host = self._hostname(name, manifest, zone)
        onboarded = self._onboarded(name, declared, manifest, host)
        # One conformance pass feeds every row-derived link.
        report = self._conformance.run()
        app_repo = self._app_repo_legs(name, report)
        ci = self._ci(manifest)
        promotion, promoted_tag = self._promotion(name)
        sync, workload = self._cluster_links(name)
        chart = self._chart_link(name)
        credentials = self._credentials(name, report)
        has_identity = manifest is not None and manifest.has_identity
        drift = self._grant_drift(name, host, has_identity)
        probe = self._probe_link(host, has_identity, promoted_tag)
        probe = StatusLink(
            probe.status if probe.status is not LinkStatus.OK else workload.status,
            f"{probe.detail}; workload: {workload.detail}",
        )
        smoke = self._smoke_link(name, zone, host, promoted_tag)
        identity_caveat = self._identity_caveat(has_identity)
        stage = self._stage(onboarded, open_pr, promotion, probe)
        if stage is DeliveryStage.SERVING and sync.status is not LinkStatus.OK:
            stage = DeliveryStage.PROMOTED
        ordered = (
            ("onboarded", onboarded),
            ("onboarding_pr", onboarding_pr),
            ("app_repo", app_repo),
            ("ci", ci),
            ("promotion", promotion),
            ("sync", sync),
            ("chart", chart),
            ("credentials", credentials),
            ("grant_drift", drift),
            ("probe", probe),
            ("smoke", smoke),
            ("identity_caveat", identity_caveat),
        )
        first = next(
            ((link_name, link) for link_name, link in ordered if link.status is not LinkStatus.OK),
            None,
        )
        summary = (
            f"stage {stage.value}: every link ok"
            if first is None
            else f"stage {stage.value}: first non-ok link {first[0]} ({first[1].status.value})"
        )
        return AppStatus(
            app=name,
            onboarded=onboarded,
            onboarding_pr=onboarding_pr,
            app_repo=app_repo,
            ci=ci,
            promotion=promotion,
            sync=sync,
            chart=chart,
            credentials=credentials,
            grant_drift=drift,
            probe=probe,
            smoke=smoke,
            identity_caveat=identity_caveat,
            stage=stage,
            summary=summary,
        )

    def _onboarding_pr(self, name: str) -> tuple[PrInfo | None, StatusLink]:
        try:
            prs = self._git.open_prs()
        except Exception as exc:  # noqa: BLE001 - a status read never crashes on a host
            logger.warning("Open PRs unreadable for the status read", exc_info=True)
            link = StatusLink(LinkStatus.SKIPPED, f"open pull requests unreadable: {exc}")
            return None, link
        pr = next((p for p in prs if p.branch == onboard_branch(name)), None)
        if pr is None:
            return None, StatusLink(LinkStatus.OK, "none open")
        detail = f"open PR #{pr.number} awaiting its automated merge (ADR-036): {pr.url}"
        return pr, StatusLink(LinkStatus.OK, detail)

    @staticmethod
    def _hostname(name: str, manifest: TeamManifest | None, zone: str) -> str:
        """The hostname the app actually serves on.

        The Gateway listener is the authority, not the app name: external-dns
        publishes the record from it, so an app whose listener names a short host
        serves there and nowhere else. Deriving `<name>.<zone>` instead probes a
        name that was never provisioned, and since `serving` requires the probe to
        answer, such an app reads `promoted` forever however healthy it is.

        `<name>.<zone>` stays the fallback for an app whose team folder is not
        readable yet - a half-onboarded app has no listener to read, and there the
        convention is all there is.
        """
        if manifest is not None and manifest.hostname:
            return manifest.hostname
        return f"{name}.{zone}" if zone else ""

    def _onboarded(
        self, name: str, declared: bool, manifest: TeamManifest | None, host: str
    ) -> StatusLink:
        host_note = f"; hostname {host}" if host else "; install zone undeclared"
        if declared and manifest is not None:
            return StatusLink(
                LinkStatus.OK,
                f"declared in foundry.yaml with teams/{name}/ present{host_note}",
            )
        if declared:
            return StatusLink(
                LinkStatus.FAILED,
                f"declared in foundry.yaml but teams/{name}/ is missing "
                f"(half-onboarded){host_note}",
            )
        if manifest is not None:
            return StatusLink(
                LinkStatus.FAILED,
                f"teams/{name}/ exists but foundry.yaml does not declare it "
                f"(half-onboarded){host_note}",
            )
        return StatusLink(
            LinkStatus.FAILED,
            f"not in foundry.yaml and no teams/{name}/ folder; the onboarding "
            f"PR has not merged yet{host_note}",
        )

    def _app_repo_legs(self, name: str, report: ConformanceReport) -> StatusLink:
        if report.exit_code not in (0, 1):
            return StatusLink(
                LinkStatus.SKIPPED,
                f"conformance suite failed to run (exit {report.exit_code}); "
                "the app-side legs could not be judged",
            )
        rows = tuple(
            row for row in report.for_app(name) if row.node_id.startswith(tuple(APP_SIDE_LEGS))
        )
        if not rows:
            return StatusLink(
                LinkStatus.SKIPPED,
                "no app-side conformance rows for this app: rows exist only "
                "for apps the manifest and teams/ already carry, so a "
                "not-yet-onboarded app skips here by construction. The gated "
                "onboarding evaluates the ci-caller, deploy-branch, and "
                "image-updater legs on the candidate state it builds, where "
                "readable artifacts pass with no waiver; this skip is not a "
                "gap in the app's own artifacts",
            )
        listing = ", ".join(f"{row.node_id}={row.outcome.value}" for row in rows)
        if any(row.outcome in (TestOutcome.FAILED, TestOutcome.ERROR) for row in rows):
            return StatusLink(LinkStatus.FAILED, listing)
        if any(row.outcome is TestOutcome.SKIPPED for row in rows):
            return StatusLink(
                LinkStatus.SKIPPED,
                f"{listing}; a skipped leg is unreadable off the repo host "
                "(repo not granted to the token, or the deploy branch not "
                "stood up yet), never a pass",
            )
        return StatusLink(LinkStatus.OK, listing)

    def _credentials(self, name: str, report: ConformanceReport) -> StatusLink:
        """The demand-grant cross-check row, read off the conformance report.

        The row is diagnostic rather than admission-gating (a grant can only
        be rendered into a teams folder an onboarding has already created), so
        the status chain is where a failing one is meant to be acted on.
        """
        if report.exit_code not in (0, 1):
            return StatusLink(
                LinkStatus.SKIPPED,
                f"conformance suite failed to run (exit {report.exit_code}); "
                "the credential demand-grant cross-check could not be judged",
            )
        row = next(
            (
                result
                for result in report.for_app(name)
                if result.node_id.startswith(DEMAND_GRANT_ROW)
            ),
            None,
        )
        if row is None:
            return StatusLink(
                LinkStatus.SKIPPED,
                "no credential row for this app: rows exist only for apps the "
                "manifest and teams/ already carry",
            )
        if row.outcome is TestOutcome.SKIPPED:
            return StatusLink(
                LinkStatus.SKIPPED,
                "the app chart's k8s/values.yaml is unreadable off the repo "
                "host (repo not granted to the studio's token), so the "
                "credentials it names could not be held to the install's grants",
            )
        if row.outcome in (TestOutcome.FAILED, TestOutcome.ERROR):
            # The row's own detail names the finding and the grant skill that
            # resolves it (the missing grant, the dormant block, the unnamed
            # credential), per credential kind. A fixed guess here named two of
            # the three kinds and misread the third (events) as one of them.
            found = (row.detail or "").strip()
            consequence = (
                "The chart and the install's grants disagree on a platform-minted "
                "credential: a pod that names a Secret nothing creates waits on it "
                "and settles in CreateContainerConfigError, and a grant the chart "
                "never consumes mints for nobody. Run the grant skill the finding "
                "names, or turn the chart's block on"
            )
            return StatusLink(
                LinkStatus.FAILED, f"{found}. {consequence}" if found else consequence
            )
        return StatusLink(
            LinkStatus.OK,
            "every platform-minted credential the chart names has the grant "
            f"in teams/{name}/ that mints it",
        )

    def _ci(self, manifest: TeamManifest | None) -> StatusLink:
        if self._app_repo is None:
            return StatusLink(
                LinkStatus.SKIPPED,
                "no app-repo source wired in this composition; CI runs unreadable",
            )
        if manifest is None or not manifest.repo_url:
            return StatusLink(
                LinkStatus.SKIPPED,
                "app repo unknown: no Application in the teams folder names a repoURL",
            )
        try:
            default = self._app_repo.default_branch(repo_url=manifest.repo_url)
            run = (
                self._app_repo.latest_workflow_run(repo_url=manifest.repo_url, branch=default)
                if default
                else None
            )
        except Exception as exc:  # noqa: BLE001 - a status read never crashes on a host
            logger.warning("CI runs unreadable for the status read", exc_info=True)
            return StatusLink(LinkStatus.SKIPPED, f"CI runs unreadable off the repo host: {exc}")
        if default is None:
            return StatusLink(
                LinkStatus.SKIPPED,
                f"default branch unreadable for {manifest.repo_url} (repo "
                "absent, or not granted to the studio's token)",
            )
        if run is None:
            return StatusLink(
                LinkStatus.SKIPPED,
                f"no completed workflow run readable on {default} of {manifest.repo_url}",
            )
        if run.conclusion == "success":
            return StatusLink(
                LinkStatus.OK,
                f"latest completed run on {default} concluded success "
                f"({run.name}, {run.completed_at}): the chain's CI-green plus "
                "artifacts-published proxy, since the shared workflow's green "
                f"path is what pushes the images and chart to GHCR. {run.url}",
            )
        return StatusLink(
            LinkStatus.FAILED,
            f"latest completed run on {default} concluded {run.conclusion} "
            f"({run.name}, {run.completed_at}): {run.url}",
        )

    def _promotion(self, name: str) -> tuple[StatusLink, str | None]:
        """The promotion link, and the app image tag it resolved.

        The tag is what the probe compares the served build against: git says
        which release was promoted, the probe says which one answers.
        """
        if self._app_repo is None:
            return (
                StatusLink(
                    LinkStatus.SKIPPED,
                    "no app-repo source wired in this composition; the deploy branch is unreadable",
                ),
                None,
            )
        promoting, annotations = self._promoting_application(name)
        if promoting is None:
            return (
                StatusLink(
                    LinkStatus.SKIPPED,
                    "no Application with Image Updater bindings in the teams "
                    "folder; nothing names the deploy branch to read",
                ),
                None,
            )
        source = (promoting.get("spec") or {}).get("source") or {}
        repo_url = str(source.get("repoURL") or "")
        branch = str(source.get("targetRevision") or "")
        env_path = str(source.get("path") or "").strip("/")
        prefix = f"{env_path}/" if env_path and env_path != "." else ""
        if not repo_url or not branch:
            return (
                StatusLink(
                    LinkStatus.SKIPPED,
                    "the Application names no repoURL or targetRevision; the "
                    "deploy branch to read is unknown",
                ),
                None,
            )
        try:
            chart = self._app_repo.deploy_values(
                repo_url=repo_url, branch=branch, path=f"{prefix}Chart.yaml"
            )
            values = self._app_repo.deploy_values(
                repo_url=repo_url, branch=branch, path=f"{prefix}values.yaml"
            )
            commit = self._app_repo.latest_commit(
                repo_url=repo_url, branch=branch, path=f"{prefix}values.yaml"
            )
        except Exception as exc:  # noqa: BLE001 - a status read never crashes on a host
            logger.warning("Deploy branch unreadable for the status read", exc_info=True)
            return (
                StatusLink(
                    LinkStatus.SKIPPED,
                    f"deploy branch unreadable off the repo host: {exc}",
                ),
                None,
            )
        if chart is None or values is None:
            return (
                StatusLink(
                    LinkStatus.SKIPPED,
                    f"{prefix}Chart.yaml or {prefix}values.yaml unreadable on "
                    f"{branch} of {repo_url} (deploy branch not stood up yet, or "
                    "not granted to the studio's token)",
                ),
                None,
            )
        pin = self._chart_pin(chart)
        bound = bound_tag_values(annotations=annotations, deploy_values=values)
        # The app's own image, not its docs sidecar: charts spell the binding
        # either way (images.app.tag, image.tag), so prefer the explicit app
        # path and fall back to the sole non-docs binding.
        candidates = [
            (path, str(value)) for path, value in bound if value is not None and "docs" not in path
        ]
        promoted_tag = next(
            (value for path, value in candidates if path.endswith("images.app.tag")),
            next((value for _, value in candidates), None),
        )
        tags = ", ".join(f"{path}={'<unset>' if value is None else value}" for path, value in bound)
        writeback = (
            f"last write-back to {prefix}values.yaml {commit.sha[:12]} at "
            f"{commit.committed_at} ({commit.message})"
            if commit is not None
            else f"last commit touching {prefix}values.yaml unreadable"
        )
        detail = (
            f"chart pinned {pin or '<no version pin found>'} on {branch}; "
            f"{tags or 'no bound image tag paths'}; {writeback}"
        )
        problems = unpromoted_bindings(app=name, annotations=annotations, deploy_values=values)
        if problems:
            return (
                StatusLink(LinkStatus.FAILED, f"{'; '.join(problems)}; {detail}"),
                promoted_tag,
            )
        return StatusLink(LinkStatus.OK, detail), promoted_tag

    def _cluster_links(self, name: str) -> tuple[StatusLink, StatusLink]:
        application, _ = self._promoting_application(name)
        if application is None or self._cluster is None:
            return sync_evidence(None, None), workload_evidence(None)
        source = (application.get("spec") or {}).get("source") or {}
        metadata = application.get("metadata") or {}
        destination = (application.get("spec") or {}).get("destination") or {}
        requested = None
        live = None
        pods = None
        try:
            if self._app_repo is not None:
                requested = self._app_repo.branch_head(
                    repo_url=str(source.get("repoURL") or ""),
                    branch=str(source.get("targetRevision") or ""),
                )
        except Exception:  # noqa: BLE001 - repo failure does not prevent cluster reads
            logger.warning("Requested deploy revision unavailable", exc_info=True)
        try:
            live = self._cluster.application(
                namespace=str(metadata.get("namespace") or "argocd"),
                name=str(metadata.get("name") or name),
            )
        except Exception:  # noqa: BLE001 - an Application read is independent of pods
            logger.warning("Application evidence unavailable", exc_info=True)
        try:
            namespace = str(destination.get("namespace") or "")
            if namespace:
                pods = self._cluster.pods(namespace=namespace)
        except Exception:  # noqa: BLE001 - unavailable external evidence stays unknown
            logger.warning("Workload evidence unavailable", exc_info=True)
        return sync_evidence(live, requested), workload_evidence(pods)

    def _chart_link(self, name: str) -> StatusLink:
        application, _ = self._promoting_application(name)
        unknown = StatusLink(LinkStatus.SKIPPED, "Published chart comparison unavailable; unknown")
        if application is None or self._app_repo is None or self._charts is None:
            return unknown
        spec = application.get("spec") or {}
        source = spec.get("source") or {}
        prefix = str(source.get("path") or "").strip("/")
        prefix = f"{prefix}/" if prefix and prefix != "." else ""
        repo_url = str(source.get("repoURL") or "")
        branch = str(source.get("targetRevision") or "")
        try:
            chart = self._app_repo.deploy_values(
                repo_url=repo_url, branch=branch, path=f"{prefix}Chart.yaml"
            )
            values = self._app_repo.deploy_values(
                repo_url=repo_url, branch=branch, path=f"{prefix}values.yaml"
            )
            if chart is None or values is None:
                return unknown
            helm = source.get("helm") or {}
            # Argo inline overrides need the same precedence as its values file.

            if helm.get("values") or helm.get("parameters") or helm.get("valueFiles"):
                return StatusLink(
                    LinkStatus.SKIPPED, "Chart comparison unknown: external Helm overrides"
                )
            values = effective_values(
                app="", chart_values=values, deploy_values={"": helm.get("valuesObject") or {}}
            )
            return self._charts.compare(
                chart=chart,
                values=values,
                release=str(
                    helm.get("releaseName")
                    or (application.get("metadata") or {}).get("name")
                    or name
                ),
                namespace=str((spec.get("destination") or {}).get("namespace") or name),
                kube_version=str(helm.get("kubeVersion") or self._kube_version),
                api_versions=tuple(helm.get("apiVersions") or self._api_versions),
            )
        except Exception:  # noqa: BLE001 - unavailable external evidence stays unknown
            logger.warning("Published chart comparison unavailable", exc_info=True)
            return unknown

    def _promoting_application(self, name: str) -> tuple[dict | None, dict[str, str]]:
        """The teams-folder Application carrying Image Updater bindings, with
        its annotations stringified; (None, {}) when the folder has none."""
        for doc in self._repository.team_documents(name):
            if doc.get("kind") != "Application":
                continue
            annotations = ((doc.get("metadata") or {}).get("annotations")) or {}
            if f"{ANNOTATION_PREFIX}image-list" in annotations:
                stringified = {str(key): str(value) for key, value in annotations.items()}
                return doc, stringified
        return None, {}

    @staticmethod
    def _chart_pin(chart: dict) -> str:
        """The published chart version prod/Chart.yaml pins: the dependency
        pin (ADR-025), falling back to the wrapper chart's own version."""
        dependencies = chart.get("dependencies")
        if isinstance(dependencies, list) and dependencies:
            first = dependencies[0]
            if isinstance(first, dict) and first.get("version"):
                return str(first["version"])
        return str(chart.get("version") or "")

    def _read_health(self, host: str) -> ProbeResult | None:
        """One read of the app's health route; None when the read could not run."""
        try:
            return self._probe.get(url=f"https://{host}/api/health")
        except Exception:  # noqa: BLE001 - a status read never crashes on a host
            logger.warning("Health read could not run for the status read", exc_info=True)
            return None

    def _served_release(
        self, host: str, promoted_tag: str | None, health: ProbeResult | None = None
    ) -> str:
        """What the running app says it is, read off its health route.

        A serving signature at the root proves something answers; it never says
        WHICH release. An app that skips its health route at the OIDC gate can
        answer that without a credential, so the probe asks and reports the build
        beside the tag promotion wrote back.

        Silent by design when the app has not adopted the skip, serves no build
        stamp, or answers anything but a readable 200: this enriches the evidence,
        it never invents a failure out of an app that predates the contract.

        A mismatch reports rather than fails. Promotion writes the tag back before
        the new pod is ready, so a disagreement is the normal state for the length
        of a rollout; failing on it would make every deploy flap.

        ``health`` is a read of the route the probe already made to judge the root;
        without one the route is read here, so no status read fetches it twice.
        """
        if health is None:
            health = self._read_health(host)
        if health is None or health.status_code != 200 or not health.body:
            return ""
        try:
            payload = json.loads(health.body)
        except ValueError:
            return ""
        version = payload.get("version") if isinstance(payload, dict) else None
        if not version:
            return ""
        if promoted_tag is None:
            return f", running {version}"
        if str(version) == promoted_tag:
            return f", running {version} - the promoted tag"
        return (
            f", running {version} while the promoted tag is {promoted_tag} "
            "(mid-rollout, or the new pod never became ready)"
        )

    def _probe_link(self, host: str, has_identity: bool, promoted_tag: str | None) -> StatusLink:
        if not host:
            return StatusLink(
                LinkStatus.SKIPPED,
                "install zone undeclared in values.yaml; no hostname to probe",
            )
        url = f"https://{host}/"
        try:
            result = self._probe.get(url=url)
        except Exception as exc:  # noqa: BLE001 - a status read never crashes on a host
            logger.warning("Probe could not run for the status read", exc_info=True)
            return StatusLink(LinkStatus.SKIPPED, f"probe of {url} could not run: {exc}")
        observed = ", ".join(f"{key}={value}" for key, value in result.headers)
        suffix = f" ({observed})" if observed else ""
        if result.status_code is None:
            return StatusLink(
                LinkStatus.FAILED,
                f"no response from {url} after {result.latency_ms}ms: {result.error}",
            )
        if result.status_code == 200:
            served = self._served_release(host, promoted_tag)
            return StatusLink(
                LinkStatus.OK,
                f"HTTP 200 from {url} in {result.latency_ms}ms: serving{served}{suffix}",
            )
        if result.status_code in (302, 401) and has_identity:
            served = self._served_release(host, promoted_tag)
            return StatusLink(
                LinkStatus.OK,
                f"HTTP {result.status_code} from {url} in {result.latency_ms}ms: "
                "serving behind its auth proxy (the identity grant makes a "
                f"302/401 at the edge the expected signature){served}{suffix}",
            )
        if result.status_code == 401 and not has_identity:
            # An app that gates its own callers answers 401 on every path; its
            # health route answering 200 is what proves it serves.
            health = self._read_health(host)
            if health is not None and health.status_code == 200:
                served = self._served_release(host, promoted_tag, health)
                return StatusLink(
                    LinkStatus.OK,
                    f"HTTP 401 from {url} in {result.latency_ms}ms: "
                    "serving behind the app's own auth (no identity grant, and "
                    f"its /api/health answers 200){served}{suffix}",
                )
        return StatusLink(
            LinkStatus.FAILED,
            f"HTTP {result.status_code} from {url} in {result.latency_ms}ms: "
            "not a serving signature (200, 302/401 behind a granted identity, "
            f"or 401 with a 200 from /api/health){suffix}",
        )

    def _smoke_link(self, name: str, zone: str, host: str, promoted_tag: str | None) -> StatusLink:
        """The app's in-cluster deployed-smoke verdict (INT-STATUS-002, ADR-047).

        The behavioral evidence the probe cannot give: the app's own chart runs
        its deployed e2e suite in-cluster against its public hostname (through
        the edge, the auth proxy, and the realm) and publishes only the verdict,
        which the platform's smoke reporter serves read-only at the docs host.
        The studio reads that URL over the edge, so the credential the smoke
        used never appears anywhere in this chain.

        Advisory like the credentials cross-check: it stays outside the stage
        derivation, and an app that has not adopted the contract reads skipped,
        never failed. A reporter that does not answer is platform trouble, not
        app evidence, so it also reads skipped with the reason. A published
        verdict is held to the contract: a result that does not parse reads
        failed, because unreadable evidence on the chain is a defect, not an
        absence. A verdict for an older tag reports the gap rather than
        failing; promotion writes the tag back before the smoke re-runs, so a
        disagreement is the normal state for the length of a rollout.
        """
        if not zone:
            return StatusLink(
                LinkStatus.SKIPPED,
                "install zone undeclared in values.yaml; no smoke reporter to read",
            )
        url = f"https://docs.{zone}/smoke/{name}.json"
        try:
            result = self._probe.get(url=url)
        except Exception as exc:  # noqa: BLE001 - a status read never crashes on a host
            logger.warning("Smoke read could not run for the status read", exc_info=True)
            return StatusLink(LinkStatus.SKIPPED, f"smoke read of {url} could not run: {exc}")
        if result.status_code is None:
            return StatusLink(
                LinkStatus.SKIPPED,
                f"smoke reporter did not answer at {url} after "
                f"{result.latency_ms}ms: {result.error}; no verdict, not an app failure",
            )
        if result.status_code == 404:
            return StatusLink(
                LinkStatus.SKIPPED,
                f"no smoke result published for this app at {url}; the "
                "in-cluster smoke contract (ADR-047) is optional",
            )
        if result.status_code != 200:
            return StatusLink(
                LinkStatus.SKIPPED,
                f"smoke reporter answered HTTP {result.status_code} at {url}: "
                "no verdict readable; platform trouble, not app evidence",
            )
        try:
            payload = json.loads(result.body)
        except ValueError:
            payload = None
        verdict = payload.get("status") if isinstance(payload, dict) else None
        if verdict not in ("passed", "failed"):
            return StatusLink(
                LinkStatus.FAILED,
                f"smoke result at {url} does not parse as the contract's "
                "result.json (status passed|failed): a published verdict must be readable",
            )
        tag = str(payload.get("tag") or "unknown")
        target = str(payload.get("target") or f"https://{host}")
        total = payload.get("total")
        finished = str(payload.get("finished_at") or "unstamped")
        if promoted_tag is None or tag == "unknown":
            tag_note = ""
        elif tag == promoted_tag:
            tag_note = " - the promoted tag"
        else:
            tag_note = (
                f" while the promoted tag is {promoted_tag} (mid-rollout, or "
                "the smoke has not re-run since promotion)"
            )
        if verdict == "passed":
            counts = f"{total} specs" if total is not None else "spec count unreported"
            return StatusLink(
                LinkStatus.OK,
                f"smoke passed on tag {tag}{tag_note}: {counts} against "
                f"{target}, finished {finished}",
            )
        failed_count = payload.get("failed")
        counts = (
            f"{failed_count} of {total} specs failed"
            if failed_count is not None and total is not None
            else "failing spec count unreported"
        )
        return StatusLink(
            LinkStatus.FAILED,
            f"smoke failed on tag {tag}{tag_note}: {counts} against {target}, finished {finished}",
        )

    def _grant_drift(self, name: str, host: str, has_identity: bool) -> StatusLink:
        """Whether the app's identity grant still matches what the canonical
        template renders for it (INT-GRANT-007).

        Advisory by construction: it is a read, and it names a difference rather
        than refusing anything. A grant is a pure function of the app name and its
        host, so a difference means someone edited the branch by hand - which is
        how a stale webOrigins outlived the template that stopped rendering it and
        how a redirect URI came to be load-bearing on one install and absent on
        the other.
        """
        if not has_identity:
            return StatusLink(LinkStatus.OK, "no identity grant to compare")
        files = {
            filename: self._repository.team_file_text(name, filename) or ""
            for filename in GRANT_FILES
        }
        result = grant_drift(
            app=name,
            grant="identity",
            rendered=render_identity_blocks(
                name, host, self._repository.default_brokers(), self._repository.login_theme()
            ),
            team_files=files,
        )
        if result.in_sync:
            return StatusLink(LinkStatus.OK, result.summary())
        return StatusLink(LinkStatus.FAILED, result.summary())

    @staticmethod
    def _identity_caveat(has_identity: bool) -> StatusLink:
        if not has_identity:
            return StatusLink(
                LinkStatus.OK,
                "no identity grant on this app; there is no OIDC round-trip to verify",
            )
        return StatusLink(LinkStatus.SKIPPED, _IDENTITY_CAVEAT)

    @staticmethod
    def _stage(
        onboarded: StatusLink,
        open_pr: PrInfo | None,
        promotion: StatusLink,
        probe: StatusLink,
    ) -> DeliveryStage:
        if onboarded.status is not LinkStatus.OK:
            if open_pr is not None:
                return DeliveryStage.PR_OPEN
            return DeliveryStage.NOT_ONBOARDED
        if promotion.status is not LinkStatus.OK:
            return DeliveryStage.AWAITING_FIRST_ARTIFACTS
        if probe.status is LinkStatus.OK:
            return DeliveryStage.SERVING
        return DeliveryStage.PROMOTED
