"""Inbound port: read one declared app."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from studio.domain.model.platform_app import PlatformApp

__all__ = ["GetAppPort"]


@runtime_checkable
class GetAppPort(Protocol):
    """Read one app's manifest entry and team-folder facts."""

    def execute(self, *, name: str) -> PlatformApp:
        ...
