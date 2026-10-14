"""Mapper: domain PlatformSetting to PlatformSettingResponse DTO."""

from __future__ import annotations

from typing import TYPE_CHECKING

from studio.adapters.inbound.http.dtos.platform_setting_response import (
    PlatformSettingResponse,
)

if TYPE_CHECKING:
    from studio.domain.model.platform_setting import PlatformSetting

__all__ = ["map_platform_setting"]


def map_platform_setting(setting: PlatformSetting) -> PlatformSettingResponse:
    """Convert a platform setting to its response DTO."""
    return PlatformSettingResponse(
        key=setting.key,
        label=setting.label,
        category=setting.category,
        unit=setting.unit,
        value=setting.value,
        default=setting.default,
        effective=setting.effective,
        source=setting.source,
        field=setting.field,
        description=setting.description,
    )
