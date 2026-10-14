"""Inbound port: freeze an app's image promotion (hold its current version)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from studio.domain.model.platform_app import PlatformApp

__all__ = ["FreezePromotionPort"]


@runtime_checkable
class FreezePromotionPort(Protocol):
    """Freeze a declared app's promotion and return it with its new mode."""

    def execute(self, *, name: str) -> PlatformApp:
        ...
