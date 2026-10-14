"""Shared test fixtures: a synthetic install checkout and a client wired to it."""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from studio.domain.model.default_broker import DefaultBroker
from studio.domain.services.identity_grant import render_identity_blocks
from studio.domain.services.team_documents import split_by_concern

# The suite exercises business behavior; the fail-closed auth gate has its own
# dedicated tests (test_auth.py) that override this.
os.environ.setdefault("STUDIO_AUTH_DISABLED", "true")

from studio.adapters.inbound.http.app import create_app
from studio.container import Container
from studio.domain.exceptions.entity_not_found_error import EntityNotFoundError
from studio.domain.model.conformance_report import ConformanceReport
from studio.domain.model.pr_info import PrInfo
from studio.domain.model.probe_result import ProbeResult
from studio.domain.model.test_outcome import TestOutcome
from studio.domain.model.test_result import TestResult

_FOUNDRY = """# Test install manifest (ADR-032). Entries sorted by name per role.
install: test
ground: lab
parts:
- name: alpha-app
  display: Alpha App
  icon: mdi-alpha
  mcp: true

# The output the install built and runs.
output:
- name: beta-app
  display: Beta App
  icon: mdi-beta
"""

_VALUES = """# How the test install is configured.
zone: lab.example.dev
tunnelId: 00000000-0000-0000-0000-000000000000
# Where this install's repositories live (githubOrgUrl, platformRepo, ciRepo):
# the organisation the studio renders every repoURL, GHCR owner, and scaffolded
# CI caller under. Declared here so the fixture exercises the ordinary case;
# tests for the pre-block fallback write their own values.yaml.
githubOrgUrl: https://github.com/Test-Org
platformRepo: foundry-platform
ciRepo: ci
operators:
  - operator@example.test
# The default brokers this install declares (ADR-045). One here, so the fixture
# exercises the ordinary case; tests that need none or several build their own.
defaultBrokers:
  - alias: google
    providerId: google
    secretRef: keycloak-google
    displayName: Google
    config:
      useJwksUrl: "true"
"""

# The same declaration in model form, for rendering the fixture's own grant.
_FIXTURE_BROKERS = (
    DefaultBroker(
        alias="google",
        provider_id="google",
        secret_ref="keycloak-google",
        display_name="Google",
        config={"useJwksUrl": "true"},
    ),
)

_ALPHA_NAMESPACE = """apiVersion: v1
kind: Namespace
metadata:
  name: alpha-app
  labels:
    gateway-access: "true"
"""

_ALPHA_GATEWAY = """# Per-app Gateway, a mirror of the other apps.
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: alpha-app
  namespace: network
  annotations:
    external-dns.alpha.kubernetes.io/target: tunnel.example.net
spec:
  gatewayClassName: traefik
  listeners:
    - name: web
      protocol: HTTP
      port: 8000
      hostname: alpha-app.lab.example.dev
"""

_ALPHA_RBAC = """apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: alpha-app-team-edit
  namespace: alpha-app
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: edit
subjects:
  - apiGroup: rbac.authorization.k8s.io
    kind: User
    name: "operator@example.test"
"""

_ALPHA_APPLICATION = """# ArgoCD Application: the platform-owned pointer at the deploy branch.
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: alpha-app
  namespace: argocd
  annotations:
    argocd-image-updater.argoproj.io/image-list: app=ghcr.io/test-org/alpha-app
    argocd-image-updater.argoproj.io/app.update-strategy: semver
    argocd-image-updater.argoproj.io/app.helm.image-name: alpha-app.image.repository
    argocd-image-updater.argoproj.io/app.helm.image-tag: alpha-app.image.tag
    argocd-image-updater.argoproj.io/write-back-method: git:secret:argocd/github-creds
    argocd-image-updater.argoproj.io/git-branch: deploy-test
    argocd-image-updater.argoproj.io/write-back-target: helmvalues:/prod/values.yaml
spec:
  project: apps
  source:
    repoURL: https://github.com/Test-Org/alpha-app
    targetRevision: deploy-test
    path: prod
  destination:
    server: https://kubernetes.default.svc
    namespace: alpha-app
"""

_ALPHA_ROUTES = """apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: alpha-app-docs
  namespace: alpha-app
  annotations:
    gethomepage.dev/enabled: "true"
    gethomepage.dev/name: Alpha App
    gethomepage.dev/description: The alpha application
    gethomepage.dev/icon: mdi-alpha
    gethomepage.dev/group: Foundry
    gethomepage.dev/widget.metrics.0.query: 'sum(rate(x{service=~"alpha-app-.*"}[1h]))'
spec:
  parentRefs:
    - name: docs
      namespace: network
  hostnames:
    - docs.lab.example.dev
  rules:
    - matches:
        - path:
            type: PathPrefix
            value: /apps/alpha-app
      backendRefs:
        - name: alpha-app-docs
          port: 80
"""

_ALPHA_FILES = {
    "namespace.yaml": _ALPHA_NAMESPACE,
    "gateway.yaml": _ALPHA_GATEWAY,
    "rbac.yaml": _ALPHA_RBAC,
    "application.yaml": _ALPHA_APPLICATION,
    "routes.yaml": _ALPHA_ROUTES,
}

_BETA_JOBS = """apiVersion: batch/v1
kind: Job
metadata:
  name: gen-pg-app-beta-app
  namespace: beta-app
  annotations:
    argocd.argoproj.io/hook: Sync
spec:
  template:
    spec:
      restartPolicy: OnFailure
      containers:
        - name: generate
          image: alpine/k8s:1.31.1
          command:
            - /bin/sh
            - -c
            - |
              kubectl create secret generic pg-app-beta-app -n beta-app
---
apiVersion: batch/v1
kind: Job
metadata:
  name: pg-beta-app-provision
  namespace: databases
  annotations:
    argocd.argoproj.io/hook: PostSync
spec:
  backoffLimit: 6
  template:
    spec:
      restartPolicy: OnFailure
      containers:
        - name: provision
          image: postgres:17-alpine
          command:
            - /bin/sh
            - -c
            - |
              echo 'GRANT "beta-app" TO CURRENT_USER WITH SET TRUE'
              echo 'CREATE DATABASE "beta-app" OWNER "beta-app"'
              echo 'REVOKE CONNECT ON DATABASE "beta-app" FROM PUBLIC'
          volumeMounts:
            - name: app-cred
              mountPath: /var/run/app-cred
              readOnly: true
      volumes:
        - name: app-cred
          secret:
            secretName: pg-app-beta-app
            optional: true
---
apiVersion: batch/v1
kind: Job
metadata:
  name: keycloak-beta-app-provision
  namespace: identity
  annotations:
    argocd.argoproj.io/hook: PostSync
spec:
  template:
    spec:
      restartPolicy: OnFailure
      containers:
        - name: config-cli
          image: adorsys/keycloak-config-cli:6.5.1-26.1.0
          env:
            - name: GOOGLE_CLIENT_ID
              valueFrom:
                secretKeyRef:
                  name: keycloak-google
                  key: clientId
            - name: GOOGLE_CLIENT_SECRET
              valueFrom:
                secretKeyRef:
                  name: keycloak-google
                  key: clientSecret
            - name: OIDC_CLIENT_SECRET
              valueFrom:
                secretKeyRef:
                  name: keycloak-beta-app
                  key: clientSecret
            - name: REALM_ADMIN_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: keycloak-beta-app
                  key: realmAdminPassword
"""

_INTENT = """INT-TEST-001:
  version: 1.0.0
  status: active
  statement: "Manifest and teams MUST agree."
  rationale: "Because tests."
  test:
    scope: integration
    component: InstallManifest
    type: invariant
  criticality: critical

INT-TEST-002:
  version: 1.0.0
  status: active
  statement: "Apps MUST ship a Dockerfile."
  rationale: "Because tests."
  test:
    scope: integration
    component: RepoStandard
    type: invariant
  criticality: high
"""


def make_report(
    *results: tuple[str, TestOutcome], exit_code: int = 0, output: str = "stub output"
) -> ConformanceReport:
    return ConformanceReport(
        exit_code=exit_code,
        results=tuple(TestResult(node_id=node, outcome=outcome) for node, outcome in results),
        output=output,
    )


def passing_report() -> ConformanceReport:
    return make_report(
        ("install/parity::manifest-teams-bijection", TestOutcome.PASSED),
        ("install/manifest::entry-shape[alpha-app]", TestOutcome.PASSED),
        ("install/manifest::entry-shape[beta-app]", TestOutcome.PASSED),
        exit_code=0,
    )


def failing_report() -> ConformanceReport:
    return make_report(
        ("install/parity::manifest-teams-bijection", TestOutcome.FAILED),
        ("install/manifest::entry-shape[alpha-app]", TestOutcome.PASSED),
        exit_code=1,
        output="stub failure output",
    )


class StubConformance:
    """Deterministic ConformanceRunner: replays a scripted report sequence."""

    def __init__(self, reports: list[ConformanceReport] | None = None) -> None:
        self._reports = reports or [passing_report()]
        self.calls = 0

    def run(self) -> ConformanceReport:
        self.calls += 1
        if len(self._reports) > 1:
            return self._reports.pop(0)
        return self._reports[0]


class FakeGitPr:
    """Recording GitPr for PR-flow tests."""

    def __init__(self) -> None:
        self.prepared: list[str] = []
        self.finalized: list[dict[str, str]] = []
        self.aborted: list[str] = []
        self.refreshes = 0
        self.open: list[PrInfo] = []
        self.direct_commits: list[dict[str, object]] = []
        self.deleted: list[str] = []
        # Branches the fake remote carries, and every PR that ever referenced
        # one: what prs_for_branch and delete_remote_branch answer from.
        self.remote_branches: set[str] = set()
        self.branch_prs: dict[str, list[PrInfo]] = {}
        self.finalize_error: Exception | None = None
        # What "upstream" does to the checkout when it is refreshed.
        self.on_refresh: Callable[[], None] | None = None

    def prepare_branch(self, name: str) -> None:
        self.prepared.append(name)

    def commit_to_deploy(self, *, paths: tuple[str, ...], commit_message: str) -> None:
        self.direct_commits.append({"paths": paths, "commit_message": commit_message})

    def finalize(
        self, *, branch: str, commit_message: str, pr_title: str, pr_body: str
    ) -> PrInfo | None:
        if self.finalize_error is not None:
            raise self.finalize_error
        self.finalized.append(
            {
                "branch": branch,
                "commit_message": commit_message,
                "pr_title": pr_title,
                "pr_body": pr_body,
            }
        )
        pr = PrInfo(
            number=7,
            title=pr_title,
            url="https://github.example/test/pulls/7",
            branch=branch,
            state="open",
            merged=False,
        )
        self.open.append(pr)
        return pr

    def abort(self, branch: str) -> None:
        self.aborted.append(branch)

    def delete_remote_branch(self, branch: str) -> bool:
        self.deleted.append(branch)
        if branch not in self.remote_branches:
            return False
        self.remote_branches.discard(branch)
        return True

    def open_prs(self) -> tuple[PrInfo, ...]:
        return tuple(self.open)

    def prs_for_branch(self, branch: str) -> tuple[PrInfo, ...]:
        return tuple(self.branch_prs.get(branch, ()))

    def get_pr(self, number: int) -> PrInfo:
        for pr in self.open:
            if pr.number == number:
                return pr
        raise EntityNotFoundError("pull request", str(number))

    def refresh(self) -> None:
        self.refreshes += 1
        if self.on_refresh is not None:
            self.on_refresh()


class FakeProbe:
    """Deterministic HttpProbe: replays canned observations, recording URLs.

    The status read probes the root for a serving signature and the health
    route for the build stamp, so ``by_url`` lets a test answer them
    differently; ``result`` is the default for anything unnamed.
    """

    def __init__(
        self,
        result: ProbeResult | None = None,
        by_url: dict[str, ProbeResult] | None = None,
    ) -> None:
        self.result = result or ProbeResult(
            status_code=200,
            latency_ms=12,
            headers=(("server", "test-edge"),),
        )
        self.by_url = by_url or {}
        self.urls: list[str] = []

    def get(self, *, url: str) -> ProbeResult:
        self.urls.append(url)
        for suffix, result in self.by_url.items():
            if url.endswith(suffix):
                return result
        return self.result


@pytest.fixture
def platform_root(tmp_path: Path) -> Path:
    """A synthetic deploy-branch checkout: manifest, values, teams/<app>/ folders."""
    root = tmp_path / "foundry-platform"
    (root / "teams").mkdir(parents=True)
    (root / "foundry.yaml").write_text(_FOUNDRY, encoding="utf-8")
    (root / "values.yaml").write_text(_VALUES, encoding="utf-8")
    (root / "intent.yaml").write_text(_INTENT, encoding="utf-8")
    alpha = root / "teams" / "alpha-app"
    alpha.mkdir()
    for filename, text in _ALPHA_FILES.items():
        (alpha / filename).write_text(text, encoding="utf-8")
    beta = root / "teams" / "beta-app"
    beta.mkdir()
    for filename, text in _ALPHA_FILES.items():
        swapped = text.replace("alpha-app", "beta-app").replace("Alpha App", "Beta App")
        swapped = swapped.replace("The alpha application", "The beta application")
        swapped = swapped.replace("mdi-alpha", "mdi-beta")
        # beta-app is output, so its homepage group is Apps, not the donor's Foundry.
        swapped = swapped.replace("gethomepage.dev/group: Foundry", "gethomepage.dev/group: Apps")
        (beta / filename).write_text(swapped, encoding="utf-8")
    # The identity grant's documents are RENDERED from the canonical template
    # rather than restated, so this fixture cannot go stale when the template
    # moves and the app reads as in sync on the drift link (INT-GRANT-007),
    # which is what a real onboarded app looks like. The database grant's jobs
    # stay hand-written: they are this fixture's own subject, not the identity
    # template's output.
    routed = dict(
        split_by_concern(
            render_identity_blocks(
                "beta-app", "beta-app.lab.example.dev", _FIXTURE_BROKERS
            )
        )
    )
    db_jobs = [
        doc.strip("\n")
        for doc in re.split(r"^---[ \t]*$", _BETA_JOBS, flags=re.MULTILINE)
        if "keycloak-beta-app-provision" not in doc
    ]
    jobs_text = "\n---\n".join([*db_jobs, routed["jobs.yaml"]])
    (beta / "jobs.yaml").write_text(jobs_text + "\n", encoding="utf-8")
    (beta / "config.yaml").write_text(routed["config.yaml"] + "\n", encoding="utf-8")
    return root


@pytest.fixture
def fake_git() -> FakeGitPr:
    return FakeGitPr()


def build_container(
    platform_root: Path,
    conformance: StubConformance,
    git_pr: FakeGitPr | None,
    http_probe: FakeProbe | None = None,
    events: object | None = None,
) -> Container:
    return Container(
        platform_root=platform_root,
        conformance=conformance,
        git_pr=git_pr,
        http_probe=http_probe or FakeProbe(),
        # Default to the logging publisher, so a test that says nothing about
        # events still exercises the same code path a grantless install runs.
        events=events,  # type: ignore[arg-type]
    )


@pytest.fixture
def client(platform_root: Path, fake_git: FakeGitPr) -> TestClient:
    """TestClient over the PR-capable composition with passing gates."""
    container = build_container(platform_root, StubConformance(), fake_git)
    return TestClient(create_app(container))


@pytest.fixture
def failing_client(platform_root: Path, fake_git: FakeGitPr) -> TestClient:
    """TestClient whose gates pass the baseline and fail the mutated tree."""
    conformance = StubConformance([passing_report(), failing_report()])
    container = build_container(platform_root, conformance, fake_git)
    return TestClient(create_app(container))


@pytest.fixture
def local_client(platform_root: Path) -> TestClient:
    """TestClient over the operator-owned local composition (no managed clone)."""
    container = build_container(platform_root, StubConformance(), None)
    return TestClient(create_app(container))
