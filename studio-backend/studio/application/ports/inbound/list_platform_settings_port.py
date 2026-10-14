"""Inbound port: list the curated platform settings and their current values."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from studio.domain.model.platform_setting import PlatformSetting

__all__ = ["ListPlatformSettingsPort"]


@runtime_checkable
class ListPlatformSettingsPort(Protocol):
    """List each curated platform knob with the value read from the deploy branch."""

    def execute(self) -> tuple[PlatformSetting, ...]:
        ...
