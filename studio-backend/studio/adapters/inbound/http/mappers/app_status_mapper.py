"""Mapper: domain AppStatus to AppStatusResponse DTO."""

from __future__ import annotations

from typing import TYPE_CHECKING

from studio.adapters.inbound.http.dtos.app_status_response import AppStatusResponse
from studio.adapters.inbound.http.dtos.status_link_response import StatusLinkResponse

if TYPE_CHECKING:
    from studio.domain.model.app_status import AppStatus
    from studio.domain.model.status_link import StatusLink

__all__ = ["map_app_status"]


def map_app_status(status: AppStatus) -> AppStatusResponse:
    """Convert an app's evidence chain to its response DTO."""
    return AppStatusResponse(
        name=status.app,
        stage=status.stage.value,
        summary=status.summary,
        onboarded=_map_link(status.onboarded),
        onboarding_pr=_map_link(status.onboarding_pr),
        app_repo=_map_link(status.app_repo),
        ci=_map_link(status.ci),
        promotion=_map_link(status.promotion),
        credentials=_map_link(status.credentials),
        grant_drift=_map_link(status.grant_drift),
        probe=_map_link(status.probe),
        smoke=_map_link(status.smoke),
        identity_caveat=_map_link(status.identity_caveat),
        sync=_map_link(status.sync),
        chart=_map_link(status.chart),
    )


def _map_link(link: StatusLink) -> StatusLinkResponse:
    return StatusLinkResponse(status=link.status.value, detail=link.detail)
