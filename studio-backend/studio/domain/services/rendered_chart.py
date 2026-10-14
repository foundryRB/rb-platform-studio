"""Canonical effective manifests for chart comparison."""

from __future__ import annotations

import json

__all__ = ["effective_manifests"]

_VERSION_LABELS = {"helm.sh/chart", "app.kubernetes.io/version"}


def _effective(value: object, checksums: dict[str, str]) -> object:
    if isinstance(value, list):
        return [_effective(item, checksums) for item in value]
    if not isinstance(value, dict):
        return value
    out = {}
    for key, item in value.items():
        if key == "metadata" and isinstance(item, dict):
            item = dict(item)
            if isinstance(item.get("labels"), dict):
                item["labels"] = {
                    k: v for k, v in item["labels"].items() if k not in _VERSION_LABELS
                }
            if isinstance(item.get("annotations"), dict):
                item["annotations"] = {
                    k: checksums.get(v, v)
                    if k.startswith("checksum/") and isinstance(v, str)
                    else v
                    for k, v in item["annotations"].items()
                }
        out[key] = _effective(item, checksums)
    return out


def effective_manifests(
    documents: list[dict],
    checksums: dict[str, str] | None = None,
) -> tuple[str, ...]:
    """Compare unordered resources while preserving semantically ordered lists."""
    return tuple(
        sorted(json.dumps(_effective(doc, checksums or {}), sort_keys=True) for doc in documents)
    )
