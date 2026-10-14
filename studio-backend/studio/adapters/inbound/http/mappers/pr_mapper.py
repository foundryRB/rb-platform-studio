"""Mapper: domain PrInfo to PrInfoResponse DTO."""

from __future__ import annotations

from typing import TYPE_CHECKING

from studio.adapters.inbound.http.dtos.cancelled_change_response import CancelledChangeResponse
from studio.adapters.inbound.http.dtos.pr_info_response import PrInfoResponse

if TYPE_CHECKING:
    from studio.domain.model.cancelled_change import CancelledChange
    from studio.domain.model.pr_info import PrInfo

__all__ = ["map_cancelled_change", "map_pr_info"]


def map_pr_info(pr: PrInfo) -> PrInfoResponse:
    """Convert a pull-request record to its response DTO."""
    return PrInfoResponse(
        number=pr.number,
        title=pr.title,
        url=pr.url,
        branch=pr.branch,
        state=pr.state,
        merged=pr.merged,
    )


def map_cancelled_change(cancelled: CancelledChange) -> CancelledChangeResponse:
    """Convert a cancel outcome to its response DTO."""
    return CancelledChangeResponse(
        branch=cancelled.branch,
        deleted=cancelled.deleted,
        prs=[map_pr_info(pr) for pr in cancelled.prs],
    )
