"""Run synchronous use-case work off the event loop, serialized.

The studio's use cases are synchronous and share one managed git checkout.
Executed directly on the event loop they block it for their whole duration -
a conformance suite is tens of seconds of GitHub reads, and was minutes of
them before those reads fanned out - so /api/health stops
answering, and three straight liveness probes at the kubelet's 1s timeout
kill the studio mid-call: a live onboarding died exactly that way, its gate
rejection report dying with the process, which the calling worker could only
read as a dead transport (INT-SRV-001).

to_thread keeps the loop - and health - answering during heavy work. The
lock preserves the serialization the blocking loop used to provide by
accident: the checkout admits one unit of work at a time, so an onboarding's
branch dance and the upstream poll's refresh never interleave.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TypeVar

from anyio import to_thread

__all__ = ["run_serialized"]

T = TypeVar("T")

_CHECKOUT_LOCK = threading.Lock()


async def run_serialized(work: Callable[[], T]) -> T:
    """Await ``work`` on a worker thread, holding the studio-wide checkout lock."""

    def _locked() -> T:
        with _CHECKOUT_LOCK:
            return work()

    return await to_thread.run_sync(_locked)
