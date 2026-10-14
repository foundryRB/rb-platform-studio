"""The shared chart's values.yaml carries no install-specific default (anti-pattern 19)."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit

import yaml

_VALUES = Path(__file__).resolve().parents[3] / "k8s" / "values.yaml"

# Patterns that are unmistakably one install's identity, never a safe shared default.
_BANNED = {
    "a Cloudflare Access team domain": r"cloudflareaccess\.com",
    "an install deploy branch": r"(?<![\w-])deploy-[a-z0-9]+",
    "a tunnel id": r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
}

_PER_INSTALL = (
    ("host",),
    ("auth", "oidc", "issuer"),
    ("config", "STUDIO_DEPLOY_BRANCH"),
    ("config", "STUDIO_MCP_ALLOWED_HOSTS"),
)

# Hosts every install shares; any other DNS name in a default is some install's zone.
_SHARED_HOSTS = ("ghcr.io", "quay.io", "docker.io", "registry.k8s.io", "github.com", "local")
_DNS_NAME = re.compile(r"(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}")
# A Secret key file name (tls.crt) reads like a DNS name.
_FILE_SUFFIXES = ("yaml", "yml", "json", "crt", "key", "pem", "jwt")
_SEPARATORS = re.compile(r"""[\s,;="'`<>()\[\]{}]+""")


def _strings(node: object) -> Iterator[str]:
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _strings(key)
            yield from _strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from _strings(value)
    elif isinstance(node, str):
        yield node


def _hosts(value: str) -> Iterator[str]:
    for token in _SEPARATORS.split(value):
        if "://" in token:
            token = urlsplit(token).netloc
        host = token.split("/", 1)[0].rsplit("@", 1)[-1].split(":", 1)[0]
        host = host.lower().strip(".").removeprefix("*.").strip(".")
        if _DNS_NAME.fullmatch(host) and host.rsplit(".", 1)[-1] not in _FILE_SUFFIXES:
            yield host


def _shared(host: str) -> bool:
    return any(host == shared or host.endswith(f".{shared}") for shared in _SHARED_HOSTS)


def test_chart_values_have_no_install_specific_defaults() -> None:
    text = _VALUES.read_text(encoding="utf-8")
    # values only: strip full-line and inline trailing comments
    values = "\n".join(re.sub(r"#.*$", "", line) for line in text.splitlines())
    for label, pattern in _BANNED.items():
        found = re.search(pattern, values)
        assert found is None, (
            f"k8s/values.yaml bakes {label} into a chart default: {found.group(0)!r}. "
            "Per-install values belong in each install's prod values, not the shared "
            "chart default (anti-pattern 19)."
        )

    chart = yaml.safe_load(text)
    for path in _PER_INSTALL:
        default = chart
        for key in path:
            default = default[key]
        assert default == "", (
            f"k8s/values.yaml defaults {'.'.join(path)} to {default!r}. It names one "
            "install's zone or branch, so it belongs in each install's prod values, not "
            "the shared chart default (anti-pattern 19)."
        )

    for value in _strings(chart):
        for host in _hosts(value):
            assert _shared(host), (
                f"k8s/values.yaml bakes the host {host!r} into a chart default ({value!r}). "
                "A zone belongs in each install's prod values, not the shared chart "
                "default (anti-pattern 19)."
            )
