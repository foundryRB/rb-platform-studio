"""Inbound port: resume a frozen app's image promotion."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from studio.domain.model.platform_app import PlatformApp

__all__ = ["ResumePromotionPort"]


@runtime_checkable
class ResumePromotionPort(Protocol):
    """Resume a declared app's promotion and return it with its new mode."""

    def execute(self, *, name: str) -> PlatformApp:
        ...
