"""HttpProbe over httpx: one cache-busted GET, redirects recorded not followed."""

from __future__ import annotations

import time
import uuid

import httpx

from studio import __version__
from studio.domain.model.probe_result import ProbeResult
from studio.logging import get_logger

__all__ = ["HttpxProbe"]

logger = get_logger(__name__)

_TIMEOUT_SECONDS = 5

# The headers worth reporting: the server banner, the redirect target, and
# anything build/version-ish an app volunteers about what it is running.
_KEY_HEADERS = ("server", "location")
_VERSIONISH = ("version", "build", "revision", "release")

# Enough of a health payload to read a build stamp from, and no more: the
# probe reports evidence, it does not mirror an app's responses.
_BODY_LIMIT = 2048


class HttpxProbe:
    """Implements HttpProbe with a single short-timeout httpx GET.

    A nonce query parameter defeats every cache between the studio and the
    app (CDN, tunnel, proxy), so the answer is the app's, not a cache's.
    Redirects are recorded (the Location header) rather than followed: a 302
    at the edge is itself evidence, and following it would trade that fact
    for whatever the auth proxy serves. Never raises; an unreachable host
    answers a ProbeResult naming the error.
    """

    def get(self, *, url: str) -> ProbeResult:
        busted = f"{url}{'&' if '?' in url else '?'}nonce={uuid.uuid4().hex}"
        headers = {"User-Agent": f"platform-studio/{__version__} app-status-probe"}
        start = time.monotonic()
        try:
            response = httpx.get(
                busted, headers=headers, timeout=_TIMEOUT_SECONDS, follow_redirects=False
            )
        except httpx.HTTPError as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            logger.info("Probe of %s failed after %dms: %s", url, latency_ms, exc)
            return ProbeResult(
                status_code=None,
                latency_ms=latency_ms,
                headers=(),
                error=f"{type(exc).__name__}: {exc}",
            )
        latency_ms = int((time.monotonic() - start) * 1000)
        kept = tuple(
            (key.lower(), value)
            for key, value in response.headers.items()
            if key.lower() in _KEY_HEADERS
            or any(token in key.lower() for token in _VERSIONISH)
        )
        logger.info("Probe of %s answered %d in %dms", url, response.status_code, latency_ms)
        return ProbeResult(
            status_code=response.status_code,
            latency_ms=latency_ms,
            headers=kept,
            body=response.text[:_BODY_LIMIT] if response.status_code == 200 else "",
        )
