"""Outbound port for effective published chart comparison."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from studio.domain.model.status_link import StatusLink

__all__ = ["ChartReader"]


@runtime_checkable
class ChartReader(Protocol):
    def compare(
        self,
        *,
        chart: dict,
        values: dict,
        release: str,
        namespace: str,
        kube_version: str,
        api_versions: tuple[str, ...],
    ) -> StatusLink: ...
