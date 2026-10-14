"""Inbound port: read one app's delivery evidence chain."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from studio.domain.model.app_status import AppStatus

__all__ = ["AppStatusPort"]


@runtime_checkable
class AppStatusPort(Protocol):
    """Report the delivery evidence chain for one app as typed links.

    The read an onboarding or build run polls to prove "live" instead of
    improvising its own checks: each link reports ok, failed, or skipped
    with the observed detail, and the derived stage reads serving only when
    promotion and probe are both ok.
    """

    def execute(self, *, name: str) -> AppStatus:
        ...
