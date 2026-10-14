"""System routes."""

from __future__ import annotations

import base64
import os

from fastapi import APIRouter, HTTPException

from studio import __version__

__all__ = ["router"]

router = APIRouter()


def _served_version() -> str:
    """The release actually running, for the delivery evidence chain.

    $APP_VERSION is the chart's image tag - the value promotion writes back - so
    the answer describes the pod rather than the source tree. The package
    constant is the local-dev fallback only: semantic-release never rewrites it,
    so on its own it is a hardcoded string, which is not freshness.
    """
    return os.environ.get("APP_VERSION") or __version__


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness/readiness probe; exempt from auth, and skipped at the OIDC gate
    so an external observer can read which release serves without a credential."""
    return {"status": "ok", "version": _served_version()}


@router.get("/agent-credential")
async def agent_credential() -> dict[str, str]:
    """The MCP HTTP Basic credential (base64 of user:password) for the in-app
    "Connect agent" one-liner.

    Reachable only by an already-authenticated caller: under scope=mcp the
    oauth2-proxy in front admits only a logged-in, allowlisted human; under
    scope=all the Basic gate covers it. Answers 503 when the credential is unset,
    mirroring the fail-closed auth posture (there is nothing to hand out).
    """
    user = os.environ.get("STUDIO_AUTH_USER", "")
    password = os.environ.get("STUDIO_AUTH_PASSWORD", "")
    if not (user and password):
        raise HTTPException(status_code=503, detail="MCP credential is not configured")
    encoded = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"credential": encoded}
