"""Response DTO for one curated platform setting."""

from __future__ import annotations

from pydantic import BaseModel

__all__ = ["PlatformSettingResponse"]


class PlatformSettingResponse(BaseModel):
    """One platform knob as the install's deploy branch currently has it.

    `value` is what the install pins, or null when it pins nothing; `default`
    is the chart's fallback; `effective` is what the component runs with. The
    three are reported separately so a caller can tell "explicitly set to 30
    days" from "inherits 30 days", which differ the moment the chart's default
    moves.
    """

    key: str
    label: str
    category: str
    unit: str
    value: str | None
    default: str
    effective: str
    source: str
    field: str
    description: str
