"""The event types this app owns, and the one safe way to state one.

REF-Events gives each domain exactly one owner, and this app owns ``platform``
by its grant. The constants below are its whole vocabulary, and the docs page
``reference/events.md`` states the same rows for consumers; a test holds the two
equal, so neither can drift (REF-Events section 3: each owner states its own
types, held by its own tests). A type is never composed at a call site. Every
row narrates an act this studio already performs, and the deploy branch stays
the datastore: an event says a change happened to it, and is never read back
as the state of an install.

``state_fact`` is where the one-way rule is enforced for every caller at once. A
publisher is contractually forbidden from raising, but a caller that trusted that
contract and was wrong would fail the act it had already committed, which is the
single failure REF-Events section 6 exists to prevent. So the guarantee is made
true here rather than assumed.
"""

from __future__ import annotations

from studio.application.ports.outbound.event_publisher import EventPublisher
from studio.logging import get_logger

__all__ = [
    "APP_OFFBOARDED",
    "APP_ONBOARDED",
    "APP_PAUSED",
    "APP_RESUMED",
    "CHANGE_OPENED",
    "CONFORMANCE_COMPLETED",
    "GRANT_ISSUED",
    "PROMOTION_FROZEN",
    "PROMOTION_RESUMED",
    "SETTING_CHANGED",
    "pr_pointer",
    "state_fact",
]

logger = get_logger(__name__)

# The registry rows this app owns (REF-Events section 3).
APP_ONBOARDED = "com.foundry.platform.app.onboarded"
APP_OFFBOARDED = "com.foundry.platform.app.offboarded"
GRANT_ISSUED = "com.foundry.platform.grant.issued"
APP_PAUSED = "com.foundry.platform.app.paused"
APP_RESUMED = "com.foundry.platform.app.resumed"
PROMOTION_FROZEN = "com.foundry.platform.promotion.frozen"
PROMOTION_RESUMED = "com.foundry.platform.promotion.resumed"
CHANGE_OPENED = "com.foundry.platform.change.opened"
SETTING_CHANGED = "com.foundry.platform.setting.changed"
CONFORMANCE_COMPLETED = "com.foundry.platform.conformance.completed"


def pr_pointer(pr: object) -> str | None:
    """The pull request as the pointer an event carries: its URL, or None.

    A ``PrInfo`` is a dataclass, and the envelope is plain JSON: handing the
    object itself to ``data`` fails serialization inside the adapter, which
    drops the event (correctly, one-way) on every act that opened a pull
    request, which in production is every act. The URL is the pointer
    REF-Events section 5 asks for, and a consumer fetches the rest from it.
    """
    url = getattr(pr, "url", None)
    return url if isinstance(url, str) and url else None


def state_fact(
    publisher: EventPublisher,
    *,
    event_type: str,
    subject: str,
    data: dict[str, object],
) -> None:
    """Publish a fact, and let nothing about it reach the caller.

    Every failure mode ends the same way: dropped, logged at warning, and the
    act that caused it completes with the outcome it already had.
    """
    try:
        publisher.publish(event_type=event_type, subject=subject, data=data)
    except Exception as exc:  # noqa: BLE001 - a publish never fails its cause
        logger.warning("dropped event %s for %s: %s", event_type, subject, exc)
