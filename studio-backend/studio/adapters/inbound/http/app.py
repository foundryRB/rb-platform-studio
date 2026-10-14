"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from mcp.server.fastmcp import FastMCP

from studio import __version__
from studio.adapters.inbound.http.auth import install_auth
from studio.adapters.inbound.http.dependencies import get_container
from studio.adapters.inbound.http.exception_handlers import register_exception_handler
from studio.adapters.inbound.http.routers import (
    apps,
    claims,
    conformance,
    onboard,
    prs,
    settings,
    sync,
    system,
)
from studio.adapters.inbound.mcp.server import build_mcp_server
from studio.adapters.inbound.work import run_serialized
from studio.container import Container
from studio.logging import configure_logging, get_logger

__all__ = ["create_app"]

logger = get_logger(__name__)

_POLL_SECONDS_ENV = "STUDIO_PLATFORM_POLL_SECONDS"
_DEFAULT_POLL_SECONDS = 300

_FRONTEND_DIST_ENV = "STUDIO_FRONTEND_DIST"


def _frontend_dir() -> Path:
    """The built SPA, copied next to the studio package by the image build
    (<project>/web/dist). Absent in native dev and tests, where vite serves it.
    $STUDIO_FRONTEND_DIST overrides the location.
    """
    env = os.environ.get(_FRONTEND_DIST_ENV)
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[4] / "web" / "dist"


def create_app(container: Container | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    The container decides capabilities: the PR surface (open PRs, refresh,
    and the upstream poll) exists only when the composition manages the
    clone. Use cases never learn where they run.
    """
    configure_logging()
    resolved = container or get_container()
    mcp_server = build_mcp_server(resolved)
    app = FastAPI(
        title="platform-studio API",
        version=__version__,
        lifespan=_lifespan(resolved, mcp_server),
    )
    app.dependency_overrides[get_container] = lambda: resolved
    # Gate the whole app (SPA + /api + /mcp) behind fail-closed HTTP Basic auth,
    # except /api/health. Disabled in dev/tests via STUDIO_AUTH_DISABLED=true.
    install_auth(app)
    register_exception_handler(app)
    app.include_router(system.router, prefix="/api", tags=["system"])
    app.include_router(apps.router, prefix="/api", tags=["apps"])
    app.include_router(claims.router, prefix="/api", tags=["claims"])
    app.include_router(settings.router, prefix="/api", tags=["settings"])
    app.include_router(conformance.router, prefix="/api", tags=["conformance"])
    app.include_router(onboard.router, prefix="/api", tags=["onboard"])
    if resolved.pr_enabled:
        app.include_router(prs.router, prefix="/api", tags=["prs"])
        app.include_router(sync.router, prefix="/api", tags=["sync"])
    # The transport lives under /mcp/. The bare path must work too (clients
    # connect to https://<host>/mcp), and it cannot rely on the router's
    # implicit slash redirect: the SPA mount at / matches /mcp first and
    # answers 405. An explicit 307 keeps the method and body.
    @app.api_route("/mcp", methods=["GET", "POST", "DELETE"], include_in_schema=False)
    async def _mcp_redirect() -> RedirectResponse:
        return RedirectResponse(url="/mcp/", status_code=307)

    app.mount("/mcp", mcp_server.streamable_http_app())
    # Serve the built SPA at / after the API and MCP mounts so those win.
    # html=True falls back to index.html for client-side routes.
    frontend = _frontend_dir()
    if frontend.is_dir():
        app.mount("/", StaticFiles(directory=str(frontend), html=True), name="frontend")
    return app


def _lifespan(
    container: Container,
    mcp_server: FastMCP,
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    """Run the MCP session manager and the upstream poll for the app's lifetime."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        poll_seconds = int(os.environ.get(_POLL_SECONDS_ENV, str(_DEFAULT_POLL_SECONDS)))
        async with mcp_server.session_manager.run():
            task: asyncio.Task[None] | None = None
            if container.pr_enabled and poll_seconds > 0:
                logger.info("Polling upstream every %d s", poll_seconds)
                task = asyncio.create_task(_poll_upstream(container, poll_seconds))
            try:
                yield
            finally:
                if task is not None:
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task

    return lifespan


async def _poll_upstream(container: Container, interval_seconds: int) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            # Through the shared checkout lock: a refresh must never interleave
            # with an in-flight onboarding's branch dance on the same clone.
            await run_serialized(container.refresh_content().execute)
        except Exception:  # noqa: BLE001 - the poll must survive transient failures
            logger.warning("Upstream poll failed; retrying next interval", exc_info=True)
