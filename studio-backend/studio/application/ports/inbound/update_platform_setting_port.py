"""Inbound port: tune one curated platform setting on the install's deploy branch."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from studio.domain.model.onboarding_result import OnboardingResult

__all__ = ["UpdatePlatformSettingPort"]


@runtime_checkable
class UpdatePlatformSettingPort(Protocol):
    """Set a curated knob's value, gated by conformance and shipped as a pull
    request against the install's deploy branch."""

    def execute(self, *, key: str, value: str) -> OnboardingResult:
        ...
