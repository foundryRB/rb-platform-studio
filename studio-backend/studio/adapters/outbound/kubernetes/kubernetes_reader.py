"""Scoped Kubernetes reads using the pod's projected service account."""

from __future__ import annotations

import os
import ssl
from pathlib import Path
from urllib.parse import quote

import httpx

__all__ = ["KubernetesReader"]


class KubernetesReader:
    """Read primary facts; absent credentials and denied reads answer unknown."""

    def __init__(
        self,
        *,
        endpoint: str = "",
        credentials: Path | None = None,
    ) -> None:
        host = os.environ.get("KUBERNETES_SERVICE_HOST", "")
        port = os.environ.get("KUBERNETES_SERVICE_PORT_HTTPS", "443")
        self._endpoint = endpoint or (f"https://{host}:{port}" if host else "")
        self._credentials = credentials or Path("/var/run/secrets/kubernetes.io/serviceaccount")

    def _get(self, path: str) -> dict | None:
        if not self._endpoint:
            return None
        try:
            # Projected tokens rotate. Read the current token for each request.
            token = (self._credentials / "token").read_text().strip()
            verify = ssl.create_default_context(cafile=str(self._credentials / "ca.crt"))
            response = httpx.get(
                f"{self._endpoint}{path}",
                headers={"Authorization": f"Bearer {token}"},
                verify=verify,
                timeout=10,
                follow_redirects=False,
            )
            response.raise_for_status()
            payload = response.json()
            return payload if isinstance(payload, dict) else None
        except (OSError, ValueError, httpx.HTTPError):
            return None

    def application(self, *, namespace: str, name: str) -> dict | None:
        return self._get(
            f"/apis/argoproj.io/v1alpha1/namespaces/{quote(namespace, safe='')}"
            f"/applications/{quote(name, safe='')}"
        )

    def pods(self, *, namespace: str) -> tuple[dict, ...] | None:
        payload = self._get(f"/api/v1/namespaces/{quote(namespace, safe='')}/pods")
        if payload is None or not isinstance(payload.get("items"), list):
            return None
        return tuple(item for item in payload["items"] if isinstance(item, dict))
