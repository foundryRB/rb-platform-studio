"""Outbound port: probe an app's public hostname over HTTPS."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from studio.domain.model.probe_result import ProbeResult

__all__ = ["HttpProbe"]


@runtime_checkable
class HttpProbe(Protocol):
    """One cache-busted, redirect-recording GET of a URL.

    The probe is the last link of the delivery evidence chain: the app
    actually answering at its public hostname. It never raises; a host that
    cannot be reached answers a ProbeResult with no status code and the
    error named, so the caller reports the link failed rather than crashing
    the whole status read.
    """

    def get(self, *, url: str) -> ProbeResult:
        """GET ``url`` once (cache-busting nonce appended, redirects recorded
        rather than followed, short timeout) and report what was observed."""
        ...
