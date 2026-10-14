"""Use case: read the curated platform settings from the deploy branch."""

from __future__ import annotations

from studio.application.ports.outbound.platform_repository import PlatformRepository
from studio.domain.model.platform_setting import PlatformSetting
from studio.domain.services.platform_settings import (
    CURATED_SETTINGS,
    VALUES_FILE,
    build_setting,
)

__all__ = ["ListPlatformSettings"]


class ListPlatformSettings:
    """Implements ListPlatformSettingsPort over the platform repository.

    Read-only: it renders each curated knob from the install's values on its
    deploy branch, alongside the chart default that holds wherever the install
    sets nothing. Tuning a knob is UpdatePlatformSetting, which writes that same
    file through the conformance gate.

    The values file is read once for the whole registry rather than once per
    knob: every curated setting addresses the same install values file, so a
    read per setting would fetch the same blob N times.
    """

    def __init__(self, repository: PlatformRepository) -> None:
        self._repository = repository

    def execute(self) -> tuple[PlatformSetting, ...]:
        values = self._repository.raw_read(VALUES_FILE)
        return tuple(build_setting(curated, values) for curated in CURATED_SETTINGS)
