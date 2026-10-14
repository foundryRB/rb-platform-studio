"""The publisher an install without a bus grant runs: it states facts to the log.

Not a test double. An app that has not been granted bus access still performs
every act that would publish, and REF-Events says such an act completes
identically whether the transport is there or not. Logging the fact keeps the
producer's behaviour observable without inventing a delivery that did not happen.
"""

from __future__ import annotations

from studio.adapters.outbound.events.cloudevent import SOURCE
from studio.logging import get_logger

__all__ = ["LoggingEventPublisher"]

logger = get_logger(__name__)


class LoggingEventPublisher:
    """Implements EventPublisher by recording the fact and delivering nothing."""

    def publish(self, *, event_type: str, subject: str, data: dict[str, object]) -> None:
        logger.info(
            "event (not published, no bus configured): type=%s subject=%s source=%s",
            event_type,
            subject,
            SOURCE,
        )
