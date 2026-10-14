"""One conformance claim from the platform's intent.yaml."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["IntentClaim"]


@dataclass(frozen=True)
class IntentClaim:
    """A CSD intent claim: the contract one conformance check attests."""

    claim_id: str
    summary: str
    status: str
    scope: str
    criticality: str
