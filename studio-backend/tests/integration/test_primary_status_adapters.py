"""Primary cluster reads and actual Helm rendering at their adapter boundaries."""

from __future__ import annotations

import shutil
import ssl
import subprocess
from pathlib import Path

import certifi
import httpx
import pytest
import yaml

from studio.adapters.outbound.helm.helm_chart_reader import HelmChartReader
from studio.adapters.outbound.kubernetes.kubernetes_reader import KubernetesReader
from studio.domain.model.link_status import LinkStatus
from studio.domain.services.rendered_chart import effective_manifests


def test_cluster_reads_scoped_targets_and_rotating_token(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "token").write_text("first")
    shutil.copyfile(certifi.where(), tmp_path / "ca.crt")
    calls = []

    def get(url: str, **kwargs: object) -> httpx.Response:
        assert isinstance(kwargs["verify"], ssl.SSLContext)
        calls.append((url, kwargs["headers"]))
        return httpx.Response(
            200, json={"items": [{"metadata": {"name": "pod"}}]}, request=httpx.Request("GET", url)
        )

    monkeypatch.setattr(httpx, "get", get)
    reader = KubernetesReader(endpoint="https://kubernetes.example", credentials=tmp_path)
    assert reader.application(namespace="argocd", name="alpha-app") is not None
    (tmp_path / "token").write_text("second")
    assert reader.pods(namespace="alpha-app") == ({"metadata": {"name": "pod"}},)
    assert calls == [
        (
            "https://kubernetes.example/apis/argoproj.io/v1alpha1/namespaces/argocd/applications/alpha-app",
            {"Authorization": "Bearer first"},
        ),
        (
            "https://kubernetes.example/api/v1/namespaces/alpha-app/pods",
            {"Authorization": "Bearer second"},
        ),
    ]


def test_denied_cluster_read_is_unknown(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "token").write_text("token")
    shutil.copyfile(certifi.where(), tmp_path / "ca.crt")
    monkeypatch.setattr(
        httpx, "get", lambda url, **kw: httpx.Response(403, request=httpx.Request("GET", url))
    )
    reader = KubernetesReader(endpoint="https://kubernetes.example", credentials=tmp_path)
    assert reader.application(namespace="argocd", name="app") is None
    assert reader.pods(namespace="app") is None


def test_unidentified_checksum_changes_remain_meaningful() -> None:
    def deployment(checksum: str) -> dict:
        return {
            "kind": "Deployment",
            "metadata": {"name": "app"},
            "spec": {"template": {"metadata": {"annotations": {"checksum/external": checksum}}}},
        }

    assert effective_manifests([deployment("one")]) != effective_manifests([deployment("two")])


def _render_status_chart(*overrides: str) -> list[dict]:
    chart = Path(__file__).resolve().parents[3] / "k8s"
    sets = [arg for value in overrides for arg in ("--set", value)]
    result = subprocess.run(
        ["helm", "template", "studio", str(chart), "--namespace", "studio", *sets],
        text=True,
        capture_output=True,
        check=True,
        timeout=60,
    )
    return [doc for doc in yaml.safe_load_all(result.stdout) if isinstance(doc, dict)]


@pytest.mark.skipif(shutil.which("helm") is None, reason="Helm runtime required")
def test_status_chart_grants_every_application_and_pod_read_only() -> None:
    docs = _render_status_chart()
    identities = [
        (
            doc["apiVersion"],
            doc["kind"],
            doc["metadata"].get("namespace", "studio"),
            doc["metadata"]["name"],
        )
        for doc in docs
    ]
    assert len(identities) == len(set(identities))
    roles = [doc for doc in docs if doc["kind"] == "Role"]
    assert [(doc["metadata"]["namespace"], doc["rules"]) for doc in roles] == [
        (
            "argocd",
            [{"apiGroups": ["argoproj.io"], "resources": ["applications"], "verbs": ["get"]}],
        )
    ]
    cluster_roles = [doc for doc in docs if doc["kind"] == "ClusterRole"]
    assert [doc["rules"] for doc in cluster_roles] == [
        [{"apiGroups": [""], "resources": ["pods"], "verbs": ["list"]}]
    ]
    bindings = [doc for doc in docs if doc["kind"] in {"RoleBinding", "ClusterRoleBinding"}]
    assert sorted(doc["kind"] for doc in bindings) == ["ClusterRoleBinding", "RoleBinding"]
    for binding in bindings:
        assert binding["subjects"] == [
            {"kind": "ServiceAccount", "name": "studio-status", "namespace": "studio"}
        ]
        granted = roles if binding["kind"] == "RoleBinding" else cluster_roles
        assert binding["roleRef"]["kind"] == granted[0]["kind"]
        assert binding["roleRef"]["name"] == granted[0]["metadata"]["name"]
        assert binding["metadata"].get("namespace") == granted[0]["metadata"].get("namespace")
    deployment = next(doc for doc in docs if doc["kind"] == "Deployment")
    assert deployment["spec"]["template"]["spec"]["serviceAccountName"] == "studio-status"


@pytest.mark.skipif(shutil.which("helm") is None, reason="Helm runtime required")
def test_status_chart_grants_nothing_with_cluster_reads_off() -> None:
    docs = _render_status_chart("clusterRead.enabled=false")
    assert not any(
        doc["kind"] in {"Role", "RoleBinding", "ClusterRole", "ClusterRoleBinding"} for doc in docs
    )
    account = next(doc for doc in docs if doc["kind"] == "ServiceAccount")
    assert account["automountServiceAccountToken"] is False


class LocalCharts(HelmChartReader):
    """Exercise Helm over packaged local charts, replacing only OCI discovery."""

    def __init__(self, sources: Path, latest: str = "2.0.0") -> None:
        super().__init__()
        self.sources = sources
        self.latest = latest

    def _latest(self, repository: str, name: str) -> str | None:
        return self.latest

    def _render(
        self,
        root: Path,
        chart: dict,
        values: dict,
        version: str,
        release: str,
        namespace: str,
        kube_version: str,
        api_versions: tuple[str, ...],
    ) -> tuple[str, ...]:
        shutil.copytree(self.sources / version, root / "sources" / version)
        chart = dict(chart)
        chart["dependencies"] = [
            dict(chart["dependencies"][0], repository=f"file://../sources/{version}")
        ]
        return super()._render(
            root, chart, values, version, release, namespace, kube_version, api_versions
        )


@pytest.mark.skipif(shutil.which("helm") is None, reason="Helm runtime required")
@pytest.mark.parametrize(
    ("changed", "expected"),
    [
        (False, LinkStatus.OK),
        (True, LinkStatus.PENDING),
    ],
)
def test_real_helm_renders_ignore_version_churn_but_detect_config(
    tmp_path: Path,
    changed: bool,
    expected: LinkStatus,
) -> None:
    sources = tmp_path / "sources"
    for version in ("1.0.0", "2.0.0"):
        folder = sources / version
        (folder / "templates").mkdir(parents=True)
        (folder / "Chart.yaml").write_text(
            yaml.safe_dump(
                {
                    "apiVersion": "v2",
                    "name": "app",
                    "version": version,
                    "appVersion": version,
                }
            )
        )
        (folder / "values.yaml").write_text("message: default\n")
        config = """apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ .Release.Name }}-config
  labels:
    helm.sh/chart: app-{{ .Chart.Version }}
    app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
data:
  message: {{ .Values.message | quote }}
"""
        if changed and version == "2.0.0":
            config += "  feature: enabled\n"
        (folder / "templates/config.yaml").write_text(config)
        (folder / "templates/deployment.yaml").write_text("""apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .Release.Name }}
spec:
  template:
    metadata:
      annotations:
        checksum/config: {{ include (print $.Template.BasePath "/config.yaml") . | sha256sum }}
    spec:
      containers:
        - name: app
          image: {{ .Values.image | quote }}
""")
        # Verify the test's artifacts are genuine Helm chart packages too.
        subprocess.run(
            ["helm", "package", str(folder), "--destination", str(folder)],
            capture_output=True,
            check=True,
            timeout=20,
        )
    chart = {
        "apiVersion": "v2",
        "name": "wrapper",
        "version": "1.0.0",
        "dependencies": [
            {"name": "app", "version": "1.0.0", "repository": "oci://registry.example/charts"}
        ],
    }
    result = LocalCharts(sources).compare(
        chart=chart,
        values={"app": {"message": "install override", "image": "app:3.0.0"}},
        release="app",
        namespace="app",
        kube_version="1.31.0",
        api_versions=(),
    )
    assert result.status is expected, result.detail
    assert "1.0.0" in result.detail and "2.0.0" in result.detail


def test_unavailable_published_chart_remains_unknown() -> None:
    result = LocalCharts(Path("unused"), latest=None).compare(
        chart={
            "dependencies": [
                {"name": "app", "version": "1.0.0", "repository": "oci://registry.example/charts"}
            ]
        },
        values={},
        release="app",
        namespace="app",
        kube_version="1.31.0",
        api_versions=(),
    )
    assert result.status is LinkStatus.SKIPPED
    assert "unknown" in result.detail


def test_oci_discovery_uses_published_tags_and_bounded_auth(monkeypatch) -> None:
    calls = []
    real_client = httpx.Client

    def reply(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/token":
            assert request.url.params["scope"] == "repository:team/charts/app:pull"
            return httpx.Response(200, json={"token": "scoped"})
        if not request.headers.get("authorization"):
            return httpx.Response(
                401,
                headers={
                    "www-authenticate": 'Bearer realm="https://registry.example/token",service="registry.example"'
                },
            )
        assert request.headers["authorization"] == "Bearer scoped"
        return httpx.Response(200, json={"tags": ["1.0.0", "1.9.0", "2.0.0", "2.1.0-rc.1"]})

    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(reply), **kwargs),
    )

    class ObservedCharts(HelmChartReader):
        def _render(
            self,
            root: Path,
            chart: dict,
            values: dict,
            version: str,
            release: str,
            namespace: str,
            kube_version: str,
            api_versions: tuple[str, ...],
        ) -> tuple[str, ...]:
            return ("same effective template",)

    result = ObservedCharts().compare(
        chart={
            "dependencies": [
                {
                    "name": "app",
                    "version": "1.0.0",
                    "repository": "oci://registry.example/team/charts",
                }
            ]
        },
        values={},
        release="app",
        namespace="app",
        kube_version="1.31.0",
        api_versions=(),
    )
    assert result.status is LinkStatus.OK
    assert "published 2.0.0" in result.detail
    assert len(calls) == 3
