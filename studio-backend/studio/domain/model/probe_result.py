"""One HTTPS probe observation of an app's public hostname."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["ProbeResult"]


@dataclass(frozen=True)
class ProbeResult:
    """What one cache-busted GET of the hostname observed.

    ``status_code`` None means no response arrived (connection failure,
    timeout, TLS error); ``error`` then names why. ``headers`` carries only
    the key headers worth reporting: server, location on a redirect, and any
    build/version-ish header the app volunteers. ``body`` is a truncated
    prefix of the response text, kept so a caller can read a build stamp off
    a health route; it is empty for a redirect, which has no body worth
    reading.
    """

    status_code: int | None
    latency_ms: int
    headers: tuple[tuple[str, str], ...]
    error: str = ""
    body: str = ""
