"""Inbound port: pause an app (scale its workload to zero)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from studio.domain.model.platform_app import PlatformApp

__all__ = ["PauseAppPort"]


@runtime_checkable
class PauseAppPort(Protocol):
    """Pause a declared app and return it with its new status."""

    def execute(self, *, name: str) -> PlatformApp:
        ...
