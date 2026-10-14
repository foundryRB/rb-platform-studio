"""Inbound port: resume a paused app."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from studio.domain.model.platform_app import PlatformApp

__all__ = ["ResumeAppPort"]


@runtime_checkable
class ResumeAppPort(Protocol):
    """Resume a declared app and return it with its new status."""

    def execute(self, *, name: str) -> PlatformApp:
        ...
