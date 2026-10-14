"""HttpProbe no-op for compositions that must not touch the network."""

from __future__ import annotations

from studio.domain.model.probe_result import ProbeResult

__all__ = ["NoopHttpProbe"]


class NoopHttpProbe:
    """Implements HttpProbe without any network call.

    Answers every probe as unreachable with the reason named, so the probe
    link reads as not evaluated rather than guessed (the contract exports and
    tests wire this double).
    """

    def get(self, *, url: str) -> ProbeResult:
        return ProbeResult(
            status_code=None,
            latency_ms=0,
            headers=(),
            error="probe disabled in this composition",
        )
