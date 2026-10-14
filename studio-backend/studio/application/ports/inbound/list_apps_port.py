"""Inbound port: list every declared app."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from studio.domain.model.platform_app import PlatformApp

__all__ = ["ListAppsPort"]


@runtime_checkable
class ListAppsPort(Protocol):
    """List the manifest entries joined with each app's team-folder facts."""

    def execute(self) -> tuple[PlatformApp, ...]:
        ...
