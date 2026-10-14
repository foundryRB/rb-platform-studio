"""App routes over the install manifest."""

from __future__ import annotations

from fastapi import APIRouter

from studio.adapters.inbound.http.dependencies import ContainerDep
from studio.adapters.inbound.http.dtos.app_response import AppResponse
from studio.adapters.inbound.http.dtos.app_status_response import AppStatusResponse
from studio.adapters.inbound.http.mappers.app_mapper import map_app
from studio.adapters.inbound.http.mappers.app_status_mapper import map_app_status
from studio.adapters.inbound.work import run_serialized

__all__ = ["router"]

router = APIRouter()


@router.get("/apps", response_model=list[AppResponse])
async def list_apps(container: ContainerDep) -> list[AppResponse]:
    """Every declared app joined with its team-folder facts."""
    return [map_app(app) for app in await run_serialized(lambda: container.list_apps().execute())]


@router.get("/apps/{name}", response_model=AppResponse)
async def get_app(name: str, container: ContainerDep) -> AppResponse:
    """One declared app: manifest entry, hostname, repo, database, MCP."""
    return map_app(await run_serialized(lambda: container.get_app().execute(name=name)))


@router.get("/apps/{name}/status", response_model=AppStatusResponse)
async def app_status(name: str, container: ContainerDep) -> AppStatusResponse:
    """One app's delivery evidence chain: each link typed ok/failed/skipped,
    plus the derived stage and a one-line summary."""
    return map_app_status(await run_serialized(lambda: container.app_status().execute(name=name)))


@router.post("/apps/{name}/pause", response_model=AppResponse)
async def pause_app(name: str, container: ContainerDep) -> AppResponse:
    """Pause an app (scale-to-zero override); direct-commits to the deploy branch."""
    return map_app(await run_serialized(lambda: container.pause_app().execute(name=name)))


@router.post("/apps/{name}/resume", response_model=AppResponse)
async def resume_app(name: str, container: ContainerDep) -> AppResponse:
    """Resume a paused app; removes the override and direct-commits to the deploy branch."""
    return map_app(await run_serialized(lambda: container.resume_app().execute(name=name)))


@router.post("/apps/{name}/promotion/freeze", response_model=AppResponse)
async def freeze_promotion(name: str, container: ContainerDep) -> AppResponse:
    """Hold the app on its current version: adds the Image Updater freeze tag
    filters; direct-commits to the deploy branch."""
    return map_app(await run_serialized(lambda: container.freeze_promotion().execute(name=name)))


@router.post("/apps/{name}/promotion/resume", response_model=AppResponse)
async def resume_promotion(name: str, container: ContainerDep) -> AppResponse:
    """Let the app take new versions again; removes the freeze tag filters and
    direct-commits to the deploy branch."""
    return map_app(await run_serialized(lambda: container.resume_promotion().execute(name=name)))
