"""Inbound port: list the platform's conformance claims."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from studio.domain.model.intent_claim import IntentClaim

__all__ = ["ListClaimsPort"]


@runtime_checkable
class ListClaimsPort(Protocol):
    """List the intent claims the conformance suite attests."""

    def execute(self) -> tuple[IntentClaim, ...]:
        ...
