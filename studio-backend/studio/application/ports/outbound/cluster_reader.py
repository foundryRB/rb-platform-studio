"""Outbound port for primary cluster evidence."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

__all__ = ["ClusterReader"]


@runtime_checkable
class ClusterReader(Protocol):
    """Read the named Application and pods in its destination namespace."""

    def application(self, *, namespace: str, name: str) -> dict | None: ...

    def pods(self, *, namespace: str) -> tuple[dict, ...] | None: ...
