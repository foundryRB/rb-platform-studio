"""Publish this app's facts to the shared NATS bus, one way and never blocking.

REF-Events section 6 is the whole design constraint here: a publish never blocks,
slows, or fails the act that caused it. An onboarding that failed because a
broker was down is the exact outcome this adapter exists to prevent, so delivery
happens off the caller's thread entirely.

The shape: ``publish`` puts the already-built envelope on a **bounded** queue and
returns. A daemon worker thread owns the NATS connection and drains it. A full
queue drops the oldest fact and logs, which is deliberate, the REF forbids
queueing into unbounded memory, and a bus is not the record of what happened
anyway; a slow or absent broker must cost memory that is capped, not memory that
grows. Nothing here is retried into the caller's latency budget and nothing is
surfaced to the caller as an error.

The connection is made lazily on the worker thread, so an unreachable broker
costs one background reconnect loop and no startup path. ``nats-py`` is imported
inside the worker for the same reason: an install with no bus grant runs the
logging publisher and never touches the import.
"""

from __future__ import annotations

import asyncio
import contextlib
import queue
import threading

from studio.adapters.outbound.events.cloudevent import envelope
from studio.logging import get_logger

__all__ = ["NatsEventPublisher"]

logger = get_logger(__name__)

# Deep enough to ride out a broker restart, shallow enough that an absent broker
# costs a bounded amount of memory forever.
_QUEUE_DEPTH = 256
# The worker waits this long between reconnect attempts. Slow on purpose: a bus
# that is down is not an incident for this app, so it is not worth polling hard.
_RECONNECT_SECONDS = 30.0


class NatsEventPublisher:
    """Implements EventPublisher over NATS, delivering on a background thread."""

    def __init__(self, *, servers: str, creds_path: str | None = None) -> None:
        self._servers = servers
        self._creds_path = creds_path
        self._queue: queue.Queue[tuple[str, bytes]] = queue.Queue(maxsize=_QUEUE_DEPTH)
        self._worker: threading.Thread | None = None
        self._lock = threading.Lock()

    def publish(self, *, event_type: str, subject: str, data: dict[str, object]) -> None:
        """State the fact and return. Never raises, never waits on delivery."""
        try:
            payload = envelope(event_type=event_type, subject=subject, data=data)
        except (TypeError, ValueError) as exc:
            # An unserializable payload is the producer's own bug, but it is
            # still not the caller's problem: the act that caused this has
            # already committed.
            logger.warning("dropped event %s: could not build envelope (%s)", event_type, exc)
            return

        self._ensure_worker()
        try:
            self._queue.put_nowait((event_type, payload))
        except queue.Full:
            with contextlib.suppress(queue.Empty):
                self._queue.get_nowait()  # drop the oldest, keep the newest
            logger.warning(
                "event queue full (depth %d); dropped an older fact to admit %s",
                _QUEUE_DEPTH,
                event_type,
            )
            try:
                self._queue.put_nowait((event_type, payload))
            except queue.Full:
                logger.warning("dropped event %s: queue still full", event_type)

    def _ensure_worker(self) -> None:
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                return
            self._worker = threading.Thread(
                target=self._run, name="nats-event-publisher", daemon=True
            )
            self._worker.start()

    def _run(self) -> None:
        try:
            asyncio.run(self._drain())
        except Exception as exc:  # noqa: BLE001 - a dead worker must never escape
            logger.warning("event publisher worker stopped: %s", exc)

    async def _drain(self) -> None:
        try:
            import nats
        except ImportError:  # pragma: no cover - only when the extra is absent
            logger.warning("nats-py is not installed; events will not be published")
            return

        connection = None
        while True:
            item = await asyncio.get_running_loop().run_in_executor(None, self._queue.get)
            event_type, payload = item
            if connection is None or not connection.is_connected:
                try:
                    connection = await nats.connect(
                        servers=[s.strip() for s in self._servers.split(",") if s.strip()],
                        user_credentials=self._creds_path or None,
                        max_reconnect_attempts=-1,
                        reconnect_time_wait=_RECONNECT_SECONDS,
                    )
                except Exception as exc:  # noqa: BLE001 - the bus may simply be down
                    logger.warning("dropped event %s: bus unreachable (%s)", event_type, exc)
                    continue
            try:
                # The subject IS the type: one registered row per subject, so a
                # consumer's wildcard filter is the type hierarchy itself.
                await connection.publish(event_type, payload)
            except Exception as exc:  # noqa: BLE001 - never surfaced to a caller
                logger.warning("dropped event %s: publish failed (%s)", event_type, exc)
