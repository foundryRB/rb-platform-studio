"""The install's declared environment list: a founding fact of foundry.yaml.

The manifest's ``environments:`` names the install's environments in order,
beside ``install:`` and ``ground:`` in the founding region a hand authors at
seeding. The FIRST entry is the entry environment: the one the platform
deploys automatically (the Image Updater bindings the skeleton renders point
at it); every other environment is manual, written only by a deliberate
promotion. Everything env-shaped derives from this one list: the deploy
branch's folders, the Application's path and write-back target, and the
conformance rows that hold them together.

An install that declares nothing keeps the legacy two-folder layout the
fleet's deploy branches were born with, so reading the declaration is safe
against a branch authored before the field existed.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

__all__ = ["LEGACY_ENVIRONMENTS", "declared_environments", "entry_environment"]

# The layout deploy branches carried before the manifest declared environments:
# ADR-025's per-env folders, dev and prod, with prod the wired one.
LEGACY_ENVIRONMENTS = ("dev", "prod")

# An environment names a folder on the deploy branch and rides into paths and
# hostnames, so it takes the DNS-label shape app and component names take.
_ENV_LABEL = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")


def declared_environments(manifest: Mapping[str, object]) -> tuple[str, ...]:
    """The ordered environment list the manifest declares, or the legacy
    layout when it declares none.

    Entries are names (``- prod``) or maps carrying one (``- name: prod``),
    so the list can grow per-environment fields later without reshaping.
    A malformed declaration raises rather than falling back: a hand wrote
    something, and silently ignoring it would deploy against a layout the
    hand did not declare.
    """
    raw = manifest.get("environments")
    if raw is None:
        return LEGACY_ENVIRONMENTS
    if not isinstance(raw, (list, tuple)) or not raw:
        raise ValueError(
            "foundry.yaml environments: must be a non-empty list of environment "
            f"names, in order (got {raw!r})"
        )
    names: list[str] = []
    for item in raw:
        name = str(item.get("name") or "") if isinstance(item, Mapping) else str(item or "")
        if not _ENV_LABEL.match(name):
            raise ValueError(
                f"foundry.yaml environments: entry {item!r} does not name an "
                "environment (a lowercase DNS label)"
            )
        if name in names:
            raise ValueError(f"foundry.yaml environments: {name!r} is declared twice")
        names.append(name)
    return tuple(names)


def entry_environment(environments: tuple[str, ...]) -> str:
    """The entry environment: the first of the declared list, the one the
    platform deploys automatically. Every other environment is manual."""
    if not environments:
        raise ValueError("an install carries at least one environment")
    return environments[0]
