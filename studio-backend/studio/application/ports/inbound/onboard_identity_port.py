"""Inbound port: grant an onboarded app its own isolated Keycloak realm."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from studio.domain.model.onboarding_result import OnboardingResult

__all__ = ["OnboardIdentityPort"]


@runtime_checkable
class OnboardIdentityPort(Protocol):
    """Prepare the install-side identity onboarding, conformance-gated.

    Renders the app's realm blocks (the keycloak-realm-<app> ConfigMap and its
    config-cli provisioning Job: own realm, realm-scoped admin, and the zero or
    more identity providers the install declares) from the studio's canonical
    template into the app's team folder (per concern file), on the same
    PR-or-working-tree path as app and database onboarding, with the same
    strict admission: a skipped app-side conformance row refuses the change
    unless ``allow_bootstrap`` waives it.
    """

    def execute(self, *, name: str, allow_bootstrap: bool = False) -> OnboardingResult:
        ...
