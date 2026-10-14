"""Inbound port: offboard an app from the install."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from studio.domain.model.onboarding_result import OnboardingResult

__all__ = ["OffboardAppPort"]


@runtime_checkable
class OffboardAppPort(Protocol):
    """Prepare the install-side offboarding of one app, conformance-gated.

    The inverse of onboarding, and what actually frees a name for reuse
    (REF-Foundry section 10) once any granted database and realm under the
    name are dropped too, since a grant for a reused name provisions onto what
    the shared instance still holds. It removes the app's entry from the
    install manifest (foundry.yaml) and deletes its whole teams/<app>/ folder
    in the same change, so the manifest-to-teams bijection stays exact. On the
    merge, pruning the Application removes the app's workloads and removing
    the Gateway, routes, Namespace, and RBAC frees the hostname and namespace;
    every manifest-derived view drops the app on the next sync with no further
    step. Removing the Namespace also deletes every volume the app's own chart
    claims in it, with its data on a Delete reclaim policy; the pull request
    merges moments after it opens, so those volumes are copied out before the
    act. A granted database or realm is stateful and held outside the
    namespace: removing its provisioning blocks stops provisioning without
    dropping the datastore or realm on the shared instances - that teardown is
    a separate, explicitly authorized runbook act, and the pull request
    enumerates every such grant so the disposition is decided, never
    defaulted. The app's own source repo is untouched. Ships as a pull request
    against the deploy branch (deployed) or stays in the working tree (local
    run).
    """

    def execute(self, *, name: str) -> OnboardingResult:
        ...
