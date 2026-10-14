"""Use case: read one declared app."""

from __future__ import annotations

from studio.application.ports.outbound.platform_repository import PlatformRepository
from studio.domain.exceptions.entity_not_found_error import EntityNotFoundError
from studio.domain.model.platform_app import PlatformApp

__all__ = ["GetApp"]


class GetApp:
    """Implements GetAppPort over the platform repository."""

    def __init__(self, repository: PlatformRepository) -> None:
        self._repository = repository

    def execute(self, *, name: str) -> PlatformApp:
        for entry in self._repository.manifest_entries():
            if entry.name == name:
                return PlatformApp(entry=entry, manifest=self._repository.team_manifest(name))
        raise EntityNotFoundError("app", name)
