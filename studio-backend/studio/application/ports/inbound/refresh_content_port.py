"""Inbound port: refresh the platform checkout from upstream."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

__all__ = ["RefreshContentPort"]


@runtime_checkable
class RefreshContentPort(Protocol):
    """Pull the upstream deploy-branch head into the managed checkout."""

    def execute(self) -> None:
        ...
