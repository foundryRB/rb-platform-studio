"""Raised when a platform setting is given a value its unit does not admit."""

from __future__ import annotations

from studio.domain.exceptions.app_error import AppError

__all__ = ["InvalidSettingValueError"]


class InvalidSettingValueError(AppError):
    """The value is not admissible for this knob.

    Refused before the gate runs rather than by it: a malformed duration
    reaches the chart as a values string the conformance suite has no opinion
    on, merges clean, and only surfaces as a component that will not start at
    the next sync.
    """

    def __init__(self, key: str, reason: str) -> None:
        super().__init__(f"invalid value for {key}: {reason}")
        self.key = key
        self.reason = reason
