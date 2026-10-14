"""Inbound port: cancel a change branch no open pull request tracks."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from studio.domain.model.cancelled_change import CancelledChange

__all__ = ["CancelOnboardingPort"]


@runtime_checkable
class CancelOnboardingPort(Protocol):
    """Clear a wedged change branch off the remote."""

    def execute(self, *, branch: str) -> CancelledChange:
        ...
