"""Outbound port: state a fact about this app's own domain on the event bus."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

__all__ = ["EventPublisher"]


@runtime_checkable
class EventPublisher(Protocol):
    """Publish one past-tense fact, and never make the caller wait on it.

    The contract is REF-Events. Two of its rules shape this port:

    - **Publishing is one-way.** An implementation MUST NOT raise, block past a
      short bound, or otherwise change the outcome of the act that caused the
      publish. A publish that cannot be delivered is dropped and logged. The
      studio's onboarding must not fail because a broker is down.
    - **The envelope is the contract, not the transport.** Callers state the
      fact (``event_type``, ``subject``, ``data``); the adapter shapes the
      CloudEvents envelope and chooses how it travels.

    ``event_type`` is one registered row from the type table, never composed at
    the call site. ``subject`` is the id of the thing the fact is about, so a
    consumer can filter without parsing ``data``.
    """

    def publish(
        self, *, event_type: str, subject: str, data: dict[str, object]
    ) -> None:
        """State the fact. Returns whether or not it was delivered."""
        ...
