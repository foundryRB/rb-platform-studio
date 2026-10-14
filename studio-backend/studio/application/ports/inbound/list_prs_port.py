"""Inbound port: list open onboarding pull requests."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from studio.domain.model.pr_info import PrInfo

__all__ = ["ListPrsPort"]


@runtime_checkable
class ListPrsPort(Protocol):
    """List the studio's open pull requests awaiting their automated merge."""

    def execute(self) -> tuple[PrInfo, ...]:
        ...
