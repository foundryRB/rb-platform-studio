"""Off-loop work tests: heavy use-case work must not starve the event loop,
and units of checkout work must never interleave (INT-SRV-001)."""

from __future__ import annotations

import asyncio
import time

from pytest_intent import intent

from studio.adapters.inbound.work import run_serialized


@intent("INT-SRV-001")
def test_slow_work_leaves_the_event_loop_free() -> None:
    """While a slow unit of work runs, the loop must keep scheduling other
    coroutines - the health endpoint's liveness under a running conformance
    suite, reduced to its mechanism."""

    async def scenario() -> float:
        slow = asyncio.ensure_future(run_serialized(lambda: time.sleep(0.5) or "done"))
        await asyncio.sleep(0)  # let the worker thread pick the work up
        started = time.monotonic()
        await asyncio.sleep(0.01)  # blocked-loop symptom: this would take ~0.5s
        elapsed = time.monotonic() - started
        assert await slow == "done"
        return elapsed

    assert asyncio.run(scenario()) < 0.3


@intent("INT-SRV-001")
def test_units_of_checkout_work_never_interleave() -> None:
    """Concurrent submissions serialize on the checkout lock: the single-writer
    guarantee the blocking loop used to provide by accident, kept on purpose."""

    active = 0
    overlapped = False

    def work() -> None:
        nonlocal active, overlapped
        active += 1
        if active > 1:
            overlapped = True
        time.sleep(0.02)
        active -= 1

    async def scenario() -> None:
        await asyncio.gather(*(run_serialized(work) for _ in range(4)))

    asyncio.run(scenario())
    assert not overlapped


@intent("INT-SRV-001")
def test_work_exceptions_reach_the_caller() -> None:
    """The gate's refusals surface through the offload unchanged - the
    rejection report must reach the calling worker, never die in a thread."""

    class Refusal(RuntimeError):
        pass

    def failing() -> None:
        raise Refusal("onboarding rejected by the conformance gates")

    async def scenario() -> str:
        try:
            await run_serialized(failing)
        except Refusal as exc:
            return str(exc)
        return ""

    assert "rejected" in asyncio.run(scenario())
