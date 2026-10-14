"""Render pinned and newest published OCI charts in a bounded Helm workspace."""

from __future__ import annotations

import copy
import hashlib
import os
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import httpx
import yaml

from studio.domain.model.link_status import LinkStatus
from studio.domain.model.status_link import StatusLink
from studio.domain.services.rendered_chart import effective_manifests

__all__ = ["HelmChartReader"]

_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


class HelmChartReader:
    """Use registry-published artifacts, with identical overrides and context."""

    def __init__(self, *, token: str = "", executable: str = "helm") -> None:
        self._token = token
        self._executable = executable

    def _latest(self, repository: str, name: str) -> str | None:
        parsed = urlparse(repository)
        if parsed.scheme != "oci" or not parsed.netloc:
            return None
        package = f"{parsed.path.strip('/')}/{name}".strip("/")
        url = f"https://{parsed.netloc}/v2/{package}/tags/list"
        auth = ("token", self._token) if self._token and parsed.netloc == "ghcr.io" else None
        with httpx.Client(timeout=10, follow_redirects=False) as client:
            response = client.get(url)
            if response.status_code == 401:
                challenge = response.headers.get("www-authenticate", "")
                fields = dict(re.findall(r'(\w+)="([^"]*)"', challenge))
                realm = fields.get("realm", "")
                # Credentials are sent only to the registry's own HTTPS realm.
                if urlparse(realm).scheme != "https" or urlparse(realm).netloc != parsed.netloc:
                    return None
                grant = client.get(
                    realm,
                    params={
                        "service": fields.get("service", parsed.netloc),
                        "scope": f"repository:{package}:pull",
                    },
                    auth=auth,
                )
                grant.raise_for_status()
                token = grant.json().get("token") or grant.json().get("access_token")
                if not token:
                    return None
                response = client.get(url, headers={"Authorization": f"Bearer {token}"})
            response.raise_for_status()
            if response.links.get("next"):
                # An incomplete listing cannot prove the newest publication.
                return None
            versions: list[tuple[tuple[int, ...], str]] = []
            for tag in response.json().get("tags") or []:
                match = _SEMVER.fullmatch(tag)
                if match:
                    versions.append((tuple(int(n) for n in match.groups()), tag))
            return max(versions)[1] if versions else None

    def _run(self, arguments: list[str], root: Path, *, password: str | None = None) -> str:
        env = dict(os.environ)
        env["HELM_CONFIG_HOME"] = str(root / "config")
        env["HELM_CACHE_HOME"] = str(root / "cache")
        env["HELM_DATA_HOME"] = str(root / "data")
        result = subprocess.run(
            [self._executable, *arguments],
            cwd=root,
            env=env,
            input=password,
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        if result.returncode:
            # Helm errors can contain credentials or rendered secret data.
            raise ValueError("Helm could not read or render the published chart")
        return result.stdout

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
        wrapper = root / version
        wrapper.mkdir()
        manifest = copy.deepcopy(chart)
        manifest["dependencies"][0]["version"] = version
        (wrapper / "Chart.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
        (wrapper / "values.yaml").write_text(yaml.safe_dump(values), encoding="utf-8")
        self._run(["dependency", "build", str(wrapper)], root)
        args = [
            "template",
            release,
            str(wrapper),
            "--namespace",
            namespace,
            "--kube-version",
            kube_version,
            "--include-crds",
        ]
        for api in api_versions:
            args.extend(["--api-versions", api])
        rendered = self._run(args, root)
        documents = []
        checksums: dict[str, str] = {}
        for fragment in re.split(r"(?m)^---\s*$", rendered):
            fragment = re.sub(r"(?m)^# Source:.*\n", "", fragment).lstrip("\n")
            doc = yaml.safe_load(fragment)
            if not isinstance(doc, dict):
                continue
            documents.append(doc)
            if doc.get("kind") not in {"ConfigMap", "Secret"}:
                continue
            canonical = hashlib.sha256(effective_manifests([doc])[0].encode()).hexdigest()
            # Only normalize hashes proven to cover a rendered config resource.
            # Unidentified hashes and effective config changes stay visible.
            for candidate in {
                fragment,
                fragment.rstrip("\n"),
                fragment.strip(),
                fragment.replace("\n", "\r\n"),
                fragment.rstrip("\n").replace("\n", "\r\n"),
            }:
                checksums[hashlib.sha256(candidate.encode()).hexdigest()] = canonical
        return effective_manifests(documents, checksums)

    def compare(
        self,
        *,
        chart: dict,
        values: dict,
        release: str,
        namespace: str,
        kube_version: str,
        api_versions: tuple[str, ...],
    ) -> StatusLink:
        dependencies = chart.get("dependencies")
        if not isinstance(dependencies, list) or len(dependencies) != 1:
            return StatusLink(
                LinkStatus.SKIPPED, "Chart comparison unknown: one OCI dependency required"
            )
        dependency = dependencies[0]
        pinned = str(dependency.get("version") or "")
        repository = str(dependency.get("repository") or "")
        name = str(dependency.get("name") or "")
        if not _SEMVER.fullmatch(pinned) or not name:
            return StatusLink(LinkStatus.SKIPPED, "Chart comparison unknown: exact pin unavailable")
        latest = None
        try:
            latest = self._latest(repository, name)
            if latest is None:
                raise ValueError("Published chart unavailable")
            with tempfile.TemporaryDirectory(prefix="studio-chart-") as directory:
                root = Path(directory)
                if self._token and urlparse(repository).netloc == "ghcr.io":
                    self._run(
                        [
                            "registry",
                            "login",
                            urlparse(repository).netloc,
                            "--username",
                            "token",
                            "--password-stdin",
                        ],
                        root,
                        password=self._token,
                    )
                pinned_render = self._render(
                    root, chart, values, pinned, release, namespace, kube_version, api_versions
                )
                newest_render = (
                    pinned_render
                    if latest == pinned
                    else self._render(
                        root,
                        chart,
                        values,
                        latest,
                        release,
                        namespace,
                        kube_version,
                        api_versions,
                    )
                )
            changed = pinned_render != newest_render
            return StatusLink(
                LinkStatus.PENDING if changed else LinkStatus.OK,
                f"chart pinned {pinned}; published {latest}; "
                + (
                    "effective templates differ; chart pin holds a published change"
                    if changed
                    else "effective templates match"
                ),
            )
        except (OSError, ValueError, httpx.HTTPError, yaml.YAMLError, subprocess.SubprocessError):
            return StatusLink(
                LinkStatus.SKIPPED,
                f"chart pinned {pinned}; published "
                f"{latest or '<unknown>'}; rendered comparison unknown",
            )
