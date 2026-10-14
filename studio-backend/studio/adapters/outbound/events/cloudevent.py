"""The CloudEvents envelope this app puts its facts in.

REF-Events fixes the envelope, and it is deliberately built here rather than
taken from a shared package: the REF is the only shared artifact, and every
producer owns its own outbound adapter. The shape is small enough to own.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

__all__ = ["SOURCE", "envelope"]

# This app as one stable URI-reference, fixed for its lifetime. A consumer
# checks provenance against it, so it does not track the hostname an install
# happens to serve the studio on.
SOURCE = "/foundry/platform-studio"


def envelope(*, event_type: str, subject: str, data: dict[str, object]) -> bytes:
    """One CloudEvent, JSON-encoded, ready to publish.

    ``id`` is unique per event because delivery is at-least-once and it is the
    consumer's dedupe key. ``time`` is when the fact became true, which is now:
    the publish happens after the act it describes has already committed.
    """
    return json.dumps(
        {
            "specversion": "1.0",
            "id": str(uuid.uuid4()),
            "source": SOURCE,
            "type": event_type,
            "subject": subject,
            "time": datetime.now(timezone.utc).isoformat(),
            "datacontenttype": "application/json",
            "data": data,
        },
        separators=(",", ":"),
    ).encode("utf-8")
