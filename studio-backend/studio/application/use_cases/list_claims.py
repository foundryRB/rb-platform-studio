"""Use case: list the platform's conformance claims."""

from __future__ import annotations

from studio.application.ports.outbound.platform_repository import PlatformRepository
from studio.domain.model.intent_claim import IntentClaim

__all__ = ["ListClaims"]


class ListClaims:
    """Implements ListClaimsPort over the platform repository."""

    def __init__(self, repository: PlatformRepository) -> None:
        self._repository = repository

    def execute(self) -> tuple[IntentClaim, ...]:
        return self._repository.claims()
