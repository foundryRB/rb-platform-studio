"""Composition root: wires adapters and use cases."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TypeVar

from studio.adapters.outbound.conformance_fs.install_conformance_runner import (
    InstallConformanceRunner,
)
from studio.adapters.outbound.events import LoggingEventPublisher, NatsEventPublisher
from studio.adapters.outbound.git_cli.cli_git_pr import CliGitPr
from studio.adapters.outbound.git_noop.noop_git_pr import NoopGitPr
from studio.adapters.outbound.github_repo.github_app_repo import GithubAppRepo
from studio.adapters.outbound.github_repo.github_app_writer import GithubAppWriter
from studio.adapters.outbound.helm.helm_chart_reader import HelmChartReader
from studio.adapters.outbound.http_probe.httpx_probe import HttpxProbe
from studio.adapters.outbound.kubernetes.kubernetes_reader import KubernetesReader
from studio.adapters.outbound.platform_fs.fs_platform_repository import FsPlatformRepository
from studio.application.ports.inbound.app_status_port import AppStatusPort
from studio.application.ports.inbound.cancel_onboarding_port import CancelOnboardingPort
from studio.application.ports.inbound.create_app_repo_port import CreateAppRepoPort
from studio.application.ports.inbound.freeze_promotion_port import FreezePromotionPort
from studio.application.ports.inbound.get_app_port import GetAppPort
from studio.application.ports.inbound.get_pr_port import GetPrPort
from studio.application.ports.inbound.list_apps_port import ListAppsPort
from studio.application.ports.inbound.list_claims_port import ListClaimsPort
from studio.application.ports.inbound.list_platform_settings_port import (
    ListPlatformSettingsPort,
)
from studio.application.ports.inbound.list_prs_port import ListPrsPort
from studio.application.ports.inbound.offboard_app_port import OffboardAppPort
from studio.application.ports.inbound.onboard_app_port import OnboardAppPort
from studio.application.ports.inbound.onboard_database_port import OnboardDatabasePort
from studio.application.ports.inbound.onboard_events_port import OnboardEventsPort
from studio.application.ports.inbound.onboard_identity_port import OnboardIdentityPort
from studio.application.ports.inbound.pause_app_port import PauseAppPort
from studio.application.ports.inbound.reconcile_app_port import ReconcileAppPort
from studio.application.ports.inbound.reconcile_identity_port import ReconcileIdentityPort
from studio.application.ports.inbound.refresh_content_port import RefreshContentPort
from studio.application.ports.inbound.resume_app_port import ResumeAppPort
from studio.application.ports.inbound.resume_promotion_port import ResumePromotionPort
from studio.application.ports.inbound.run_conformance_port import RunConformancePort
from studio.application.ports.inbound.update_platform_setting_port import (
    UpdatePlatformSettingPort,
)
from studio.application.ports.outbound.app_repo_source import AppRepoSource
from studio.application.ports.outbound.app_repo_writer import AppRepoWriter
from studio.application.ports.outbound.conformance_runner import ConformanceRunner
from studio.application.ports.outbound.event_publisher import EventPublisher
from studio.application.ports.outbound.git_pr import GitPr
from studio.application.ports.outbound.http_probe import HttpProbe
from studio.application.services.gated_change import GatedChange
from studio.application.use_cases.cancel_onboarding import CancelOnboarding
from studio.application.use_cases.create_app_repo import CreateAppRepo
from studio.application.use_cases.freeze_promotion import FreezePromotion
from studio.application.use_cases.get_app import GetApp
from studio.application.use_cases.get_app_status import GetAppStatus
from studio.application.use_cases.get_pr import GetPr
from studio.application.use_cases.list_apps import ListApps
from studio.application.use_cases.list_claims import ListClaims
from studio.application.use_cases.list_platform_settings import ListPlatformSettings
from studio.application.use_cases.list_prs import ListPrs
from studio.application.use_cases.offboard_app import OffboardApp
from studio.application.use_cases.onboard_app import OnboardApp
from studio.application.use_cases.onboard_database import OnboardDatabase
from studio.application.use_cases.onboard_events import OnboardEvents
from studio.application.use_cases.onboard_identity import OnboardIdentity
from studio.application.use_cases.pause_app import PauseApp
from studio.application.use_cases.reconcile_app import ReconcileApp
from studio.application.use_cases.reconcile_identity import ReconcileIdentity
from studio.application.use_cases.refresh_content import RefreshContent
from studio.application.use_cases.resume_app import ResumeApp
from studio.application.use_cases.resume_promotion import ResumePromotion
from studio.application.use_cases.run_conformance import RunConformance
from studio.application.use_cases.update_platform_setting import UpdatePlatformSetting
from studio.domain.exceptions.sync_failed_error import SyncFailedError

__all__ = ["Container", "resolve_platform_root"]

_T = TypeVar("_T")

_PLATFORM_ROOT_ENV = "STUDIO_PLATFORM_ROOT"
_PLATFORM_REPO_URL_ENV = "STUDIO_PLATFORM_REPO_URL"
# Two credentials, two blast radii (named grants, not one catch-all token):
# STUDIO_GITHUB_TOKEN writes the platform repo (contents + pull requests,
# read/write, that one repository) - the PR surface. STUDIO_FLEET_READ_TOKEN
# reads the fleet's app repos (contents read-only, every app repository) -
# the conformance legs and the status read's evidence chain. When the read
# token is unset the write token serves both, which is the historical
# single-token deployment; splitting them means a leaked read credential
# cannot touch the install branch.
_GITHUB_TOKEN_ENV = "STUDIO_GITHUB_TOKEN"
_FLEET_READ_TOKEN_ENV = "STUDIO_FLEET_READ_TOKEN"
# The third named grant: contents read/write on the fleet's app repos, repo
# delete (create_app_repo's rollback of a scaffold that cannot land), plus
# packages read on the org (the GHCR tag lookup the deploy-branch bootstrap
# resolves its pins from). It powers two acts, create_app_repo and
# onboard_app standing up the deploy-<install> branch. Like the read token
# it falls back to STUDIO_GITHUB_TOKEN: the deployed reality is one broad
# PAT that already carries these permissions, and the named envs exist so an
# operator CAN split the blast radii, not so the features sit dark until
# someone mints three tokens. A token missing the packages grant does not
# refuse - latest_semver_tag answers None and onboard_app leaves the deploy
# branch to the runbook, which reads as "CI has not published yet".
_FLEET_WRITE_TOKEN_ENV = "STUDIO_FLEET_WRITE_TOKEN"
_GIT_AUTHOR_NAME_ENV = "STUDIO_GIT_AUTHOR_NAME"
_GIT_AUTHOR_EMAIL_ENV = "STUDIO_GIT_AUTHOR_EMAIL"
_DEPLOY_BRANCH_ENV = "STUDIO_DEPLOY_BRANCH"
_SELF_APP_ENV = "STUDIO_SELF_APP"
# The event bus (foundry-platform ADR-041). Both unset is the ordinary state for
# an install whose studio holds no bus grant: it then states its facts to the log
# and every act completes exactly as it would with a broker up, which is the
# one-way rule rather than a fallback.
_NATS_SERVERS_ENV = "STUDIO_NATS_SERVERS"
_NATS_CREDS_ENV = "STUDIO_NATS_CREDS"
_DEFAULT_SELF_APP = "platform-studio"


def resolve_platform_root() -> Path:
    """The sibling clone is named by the repo URL because a fleet may prefix its repositories."""
    env = os.environ.get(_PLATFORM_ROOT_ENV)
    if env:
        return Path(env)
    workspace = Path(__file__).resolve().parents[3]
    return workspace / _platform_repo_dirname()


def _platform_repo_dirname() -> str:
    """The sibling directory name the platform repo is cloned into: the last
    segment of $STUDIO_PLATFORM_REPO_URL, ".git" and any trailing slash removed.
    Absent or unusable, the upstream default."""
    remote = (os.environ.get(_PLATFORM_REPO_URL_ENV) or "").strip().rstrip("/")
    if not remote:
        return "foundry-platform"
    name = remote.rsplit("/", 1)[-1].removesuffix(".git")
    return name or "foundry-platform"


def resolve_deploy_branch() -> str | None:
    """The install's deploy branch (STUDIO_DEPLOY_BRANCH, ADR-032). No default:
    a fallback lets a misconfigured install write its onboardings into another
    install's branch. PR-mode fails closed without it; the local no-repo
    composition never writes."""
    return os.environ.get(_DEPLOY_BRANCH_ENV)


def _resolve_git_pr(root: Path, deploy_branch: str | None) -> GitPr:
    """Managed clone when a platform repo URL is configured, no-op otherwise.

    The presence of $STUDIO_PLATFORM_REPO_URL is the deployment signal: the
    deployed studio owns its clone (parked on the install's deploy branch) and
    opens pull requests; the local run edits a working tree the operator
    commits themselves. PR-mode is fail-closed on missing configuration: a URL
    without a deploy branch, or without a token, refuses to start rather than
    running a studio that would write to the wrong install or cannot publish
    what it prepares.
    """
    remote_url = os.environ.get(_PLATFORM_REPO_URL_ENV)
    if not remote_url:
        return NoopGitPr()
    if not deploy_branch:
        raise SyncFailedError(
            f"{_PLATFORM_REPO_URL_ENV} is set but {_DEPLOY_BRANCH_ENV} is not; "
            "PR-mode needs the install's deploy branch named explicitly. There is "
            "no default: an env-specific fallback risks writing onboardings into "
            "the wrong install's branch."
        )
    token = os.environ.get(_GITHUB_TOKEN_ENV, "")
    if not token:
        raise SyncFailedError(
            f"{_PLATFORM_REPO_URL_ENV} is set but {_GITHUB_TOKEN_ENV} is not; "
            "PR-mode needs a fine-grained PAT granting the PLATFORM repo "
            "contents + pull requests, read/write. (Fleet app-repo reads ride "
            f"{_FLEET_READ_TOKEN_ENV} when set, falling back to this token - "
            "the fallback is the historical single-token deployment and makes "
            "that token broader than this message alone suggests.)"
        )
    git = CliGitPr(
        root,
        remote_url=remote_url,
        token=token,
        deploy_branch=deploy_branch,
        author_name=os.environ.get(_GIT_AUTHOR_NAME_ENV, "platform-studio"),
        author_email=os.environ.get(_GIT_AUTHOR_EMAIL_ENV, "platform-studio@localhost"),
    )
    git.ensure_ready()
    return git


def _check(instance: object, port: type[_T]) -> _T:
    if not isinstance(instance, port):
        raise TypeError(f"{type(instance).__name__} does not satisfy {port.__name__}")
    return instance


def _resolve_event_publisher() -> EventPublisher:
    """The bus publisher this install is configured for, or the logging one.

    An install with no bus grant is the ordinary case, not a degraded one: the
    studio still performs every act that would publish and records the fact, and
    the act's outcome is identical either way (REF-Events section 6).
    """
    servers = os.environ.get(_NATS_SERVERS_ENV, "").strip()
    if not servers:
        return LoggingEventPublisher()
    return NatsEventPublisher(
        servers=servers,
        creds_path=os.environ.get(_NATS_CREDS_ENV, "").strip() or None,
    )


class Container:
    """Instantiates outbound adapters once and builds use cases on demand."""

    def __init__(
        self,
        platform_root: Path | None = None,
        conformance: ConformanceRunner | None = None,
        git_pr: GitPr | None = None,
        self_app: str | None = None,
        http_probe: HttpProbe | None = None,
        app_repo: AppRepoSource | None = None,
        app_writer: AppRepoWriter | None = None,
        events: EventPublisher | None = None,
    ) -> None:
        root = platform_root or resolve_platform_root()
        self._events = events or _resolve_event_publisher()
        self._git = git_pr or _resolve_git_pr(root, resolve_deploy_branch())
        self._repository = FsPlatformRepository(root)
        # The deployed composition (the one that opens PRs) also reads each
        # app's team-owned delivery legs off the repo host: the deploy values
        # for the promotion rows, and the CI caller plus the deploy branch for
        # the delivery rows; without that signal (local runs, tests) those
        # rows report skipped. The status read shares the same source for its
        # ci and promotion links.
        self._app_repo = app_repo or (
            GithubAppRepo(
                os.environ.get(_FLEET_READ_TOKEN_ENV) or os.environ.get(_GITHUB_TOKEN_ENV, "")
            )
            if os.environ.get(_PLATFORM_REPO_URL_ENV)
            else None
        )
        write_token = os.environ.get(_FLEET_WRITE_TOKEN_ENV) or os.environ.get(
            _GITHUB_TOKEN_ENV, ""
        )
        self._app_writer = app_writer or (
            GithubAppWriter(write_token)
            if write_token and os.environ.get(_PLATFORM_REPO_URL_ENV)
            else None
        )
        # Two venues, one suite (ADR-032 discipline made explicit): the
        # standing runner judges only install-owned surfaces, so an app team
        # growing its released images never flips the install report red; the
        # act runner adds the cross-repo agreement rows (promotes,
        # released-set, docs-image) for the gates, the one place they are
        # resolvable. An injected runner (tests) serves both venues.
        self._conformance = conformance or InstallConformanceRunner(root, self._app_repo)
        self._act_conformance = conformance or InstallConformanceRunner(
            root, self._app_repo, act_rows=True
        )
        self._probe = http_probe or HttpxProbe()
        self._self_app = self_app or os.environ.get(_SELF_APP_ENV, _DEFAULT_SELF_APP)

    @property
    def pr_enabled(self) -> bool:
        """Whether this composition publishes onboardings as pull requests."""
        return not isinstance(self._git, NoopGitPr)

    def list_apps(self) -> ListAppsPort:
        return _check(ListApps(self._repository), ListAppsPort)

    def get_app(self) -> GetAppPort:
        return _check(GetApp(self._repository), GetAppPort)

    def app_status(self) -> AppStatusPort:
        return _check(
            GetAppStatus(
                repository=self._repository,
                conformance=self._conformance,
                git=self._git,
                probe=self._probe,
                app_repo=self._app_repo,
                cluster=KubernetesReader()
                if os.environ.get("STUDIO_CLUSTER_READ") == "true"
                else None,
                charts=HelmChartReader(
                    token=os.environ.get(_FLEET_READ_TOKEN_ENV)
                    or os.environ.get(_GITHUB_TOKEN_ENV, "")
                ),
                kube_version=os.environ.get("STUDIO_CHART_KUBE_VERSION", "1.31.0"),
                api_versions=tuple(
                    filter(None, os.environ.get("STUDIO_CHART_API_VERSIONS", "").split(","))
                ),
            ),
            AppStatusPort,
        )

    def list_claims(self) -> ListClaimsPort:
        return _check(ListClaims(self._repository), ListClaimsPort)

    def list_platform_settings(self) -> ListPlatformSettingsPort:
        return _check(ListPlatformSettings(self._repository), ListPlatformSettingsPort)

    def update_platform_setting(self) -> UpdatePlatformSettingPort:
        return _check(
            UpdatePlatformSetting(self._repository, self._gated_change(), self._events),
            UpdatePlatformSettingPort,
        )

    def run_conformance(self) -> RunConformancePort:
        return _check(RunConformance(self._conformance, self._events), RunConformancePort)

    def onboard_app(self) -> OnboardAppPort:
        return _check(
            OnboardApp(
                self._repository,
                self._gated_change(),
                app_repo=self._app_repo,
                app_writer=self._app_writer,
                events=self._events,
            ),
            OnboardAppPort,
        )

    def create_app_repo(self) -> CreateAppRepoPort:
        return _check(
            CreateAppRepo(
                self._repository,
                app_repo=self._app_repo,
                app_writer=self._app_writer,
            ),
            CreateAppRepoPort,
        )

    def offboard_app(self) -> OffboardAppPort:
        return _check(
            OffboardApp(self._repository, self._gated_change(), self._self_app, self._events),
            OffboardAppPort,
        )

    def reconcile_app(self) -> ReconcileAppPort:
        return _check(
            ReconcileApp(self._repository, self._gated_change()),
            ReconcileAppPort,
        )

    def reconcile_identity(self) -> ReconcileIdentityPort:
        return _check(
            ReconcileIdentity(self._repository, self._gated_change()),
            ReconcileIdentityPort,
        )

    def onboard_database(self) -> OnboardDatabasePort:
        return _check(
            OnboardDatabase(self._repository, self._gated_change(), self._events),
            OnboardDatabasePort,
        )

    def onboard_identity(self) -> OnboardIdentityPort:
        return _check(
            OnboardIdentity(self._repository, self._gated_change(), self._events),
            OnboardIdentityPort,
        )

    def onboard_events(self) -> OnboardEventsPort:
        return _check(
            OnboardEvents(self._repository, self._gated_change(), self._events),
            OnboardEventsPort,
        )

    def pause_app(self) -> PauseAppPort:
        return _check(
            PauseApp(self._repository, self._git, self._self_app, self._events), PauseAppPort
        )

    def resume_app(self) -> ResumeAppPort:
        return _check(ResumeApp(self._repository, self._git, self._events), ResumeAppPort)

    def freeze_promotion(self) -> FreezePromotionPort:
        return _check(
            FreezePromotion(self._repository, self._git, self._events), FreezePromotionPort
        )

    def resume_promotion(self) -> ResumePromotionPort:
        return _check(
            ResumePromotion(self._repository, self._git, self._events), ResumePromotionPort
        )

    def list_prs(self) -> ListPrsPort:
        return _check(ListPrs(self._git), ListPrsPort)

    def get_pr(self) -> GetPrPort:
        return _check(GetPr(self._git), GetPrPort)

    def cancel_onboarding(self) -> CancelOnboardingPort:
        return _check(CancelOnboarding(self._git), CancelOnboardingPort)

    def refresh_content(self) -> RefreshContentPort:
        return _check(RefreshContent(self._git), RefreshContentPort)

    def _gated_change(self) -> GatedChange:
        return GatedChange(self._repository, self._act_conformance, self._git, self._events)
