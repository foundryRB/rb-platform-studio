"""Use case: list every declared app with its team-folder facts."""

from __future__ import annotations

from studio.application.ports.outbound.platform_repository import PlatformRepository
from studio.domain.model.platform_app import PlatformApp

__all__ = ["ListApps"]


class ListApps:
    """Implements ListAppsPort over the platform repository."""

    def __init__(self, repository: PlatformRepository) -> None:
        self._repository = repository

    def execute(self) -> tuple[PlatformApp, ...]:
        return tuple(
            PlatformApp(entry=entry, manifest=self._repository.team_manifest(entry.name))
            for entry in self._repository.manifest_entries()
        )
