"""Onboarding routes: the gated writes."""

from __future__ import annotations

from fastapi import APIRouter

from studio.adapters.inbound.http.dependencies import ContainerDep
from studio.adapters.inbound.http.dtos.create_app_repo_request import CreateAppRepoRequest
from studio.adapters.inbound.http.dtos.offboard_app_request import OffboardAppRequest
from studio.adapters.inbound.http.dtos.onboard_app_request import OnboardAppRequest
from studio.adapters.inbound.http.dtos.onboard_database_request import OnboardDatabaseRequest
from studio.adapters.inbound.http.dtos.onboard_events_request import OnboardEventsRequest
from studio.adapters.inbound.http.dtos.onboard_identity_request import OnboardIdentityRequest
from studio.adapters.inbound.http.dtos.onboarding_result_response import (
    OnboardingResultResponse,
)
from studio.adapters.inbound.http.dtos.reconcile_app_request import ReconcileAppRequest
from studio.adapters.inbound.http.dtos.reconcile_identity_request import (
    ReconcileIdentityRequest,
)
from studio.adapters.inbound.http.dtos.repo_scaffold_response import RepoScaffoldResponse
from studio.adapters.inbound.http.mappers.onboarding_mapper import map_onboarding_result
from studio.adapters.inbound.work import run_serialized

__all__ = ["router"]

router = APIRouter()


@router.post("/onboard/app", response_model=OnboardingResultResponse)
async def onboard_app(
    request: OnboardAppRequest, container: ContainerDep
) -> OnboardingResultResponse:
    """Prepare the install-side app onboarding; gated, PR-shipped against the deploy branch."""
    return map_onboarding_result(
        await run_serialized(
            lambda: container.onboard_app().execute(
                name=request.name,
                display_name=request.display_name,
                description=request.description,
                icon=request.icon,
                expose_mcp=request.expose_mcp,
                role=request.role,
                image_components=request.image_components,
                repo=request.repo,
                allow_bootstrap=request.allow_bootstrap,
            )
        )
    )


@router.post("/repos/app", response_model=RepoScaffoldResponse)
async def create_app_repo(
    request: CreateAppRepoRequest, container: ContainerDep
) -> RepoScaffoldResponse:
    """Create a new org app repo pre-templated with the REF-Foundry contract."""
    result = await run_serialized(
        lambda: container.create_app_repo().execute(
            name=request.name,
            display_name=request.display_name,
            description=request.description,
            repo=request.repo,
        )
    )
    return RepoScaffoldResponse(
        name=result.name,
        repo_url=result.repo_url,
        branch=result.branch,
        deploy_branch=result.deploy_branch,
        files=result.files,
        image_components=result.image_components,
    )


@router.post("/offboard/app", response_model=OnboardingResultResponse)
async def offboard_app(
    request: OffboardAppRequest, container: ContainerDep
) -> OnboardingResultResponse:
    """Prepare the install-side app offboarding; gated, PR-shipped against the deploy branch.

    The merge prunes the app's namespace with every volume its chart claims,
    their data too on a Delete reclaim policy; copy those out before the call.
    """
    return map_onboarding_result(
        await run_serialized(
            lambda: container.offboard_app().execute(name=request.name)
        )
    )


@router.post("/reconcile/app", response_model=OnboardingResultResponse)
async def reconcile_app(
    request: ReconcileAppRequest, container: ContainerDep
) -> OnboardingResultResponse:
    """Re-render an app's team folder against a fresh declaration; gated, PR-shipped."""
    return map_onboarding_result(
        await run_serialized(
            lambda: container.reconcile_app().execute(
                name=request.name,
                image_components=request.image_components,
                description=request.description,
                repo=request.repo,
                allow_bootstrap=request.allow_bootstrap,
            )
        )
    )


@router.post("/reconcile/identity", response_model=OnboardingResultResponse)
async def reconcile_identity(
    request: ReconcileIdentityRequest, container: ContainerDep
) -> OnboardingResultResponse:
    """Re-render an app's realm grant against the install's declaration; gated, PR-shipped."""
    return map_onboarding_result(
        await run_serialized(
            lambda: container.reconcile_identity().execute(
                name=request.name, allow_bootstrap=request.allow_bootstrap
            )
        )
    )


@router.post("/onboard/database", response_model=OnboardingResultResponse)
async def onboard_database(
    request: OnboardDatabaseRequest, container: ContainerDep
) -> OnboardingResultResponse:
    """Prepare an app's database grant; gated, PR-shipped against the deploy branch."""
    return map_onboarding_result(
        await run_serialized(
            lambda: container.onboard_database().execute(
                name=request.name, allow_bootstrap=request.allow_bootstrap
            )
        )
    )


@router.post("/onboard/identity", response_model=OnboardingResultResponse)
async def onboard_identity(
    request: OnboardIdentityRequest, container: ContainerDep
) -> OnboardingResultResponse:
    """Prepare an app's Keycloak realm grant; gated, PR-shipped against the deploy branch."""
    return map_onboarding_result(
        await run_serialized(
            lambda: container.onboard_identity().execute(
                name=request.name, allow_bootstrap=request.allow_bootstrap
            )
        )
    )


@router.post("/onboard/events", response_model=OnboardingResultResponse)
async def onboard_events(
    request: OnboardEventsRequest, container: ContainerDep
) -> OnboardingResultResponse:
    """Prepare an app's event-bus grant; gated, PR-shipped against the deploy branch."""
    return map_onboarding_result(
        await run_serialized(
            lambda: container.onboard_events().execute(
                name=request.name,
                domains=request.domains,
                allow_bootstrap=request.allow_bootstrap,
            )
        )
    )
