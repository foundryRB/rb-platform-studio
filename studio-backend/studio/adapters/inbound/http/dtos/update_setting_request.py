"""Request DTO: tune one curated platform setting."""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = ["UpdateSettingRequest"]


class UpdateSettingRequest(BaseModel):
    """The new value for the knob named in the path.

    Shape only here: what counts as a valid value is the knob's own unit
    (a duration for the retention horizons), judged in the domain, so the rule
    lives with the registry that declares the unit rather than being restated
    per transport.
    """

    value: str = Field(min_length=1, description="The knob's new value, e.g. '720h'")
