"""Inbound port: grant an onboarded app its own isolated database."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from studio.domain.model.onboarding_result import OnboardingResult

__all__ = ["OnboardDatabasePort"]


@runtime_checkable
class OnboardDatabasePort(Protocol):
    """Prepare the install-side database onboarding, conformance-gated.

    Renders the app's provisioning Job (database, least-privilege owner role,
    connect lockdown, credential mirror) from the studio's canonical template
    into the app's team folder (per concern file), on the same
    PR-or-working-tree path as app onboarding, with the same strict admission:
    a skipped app-side conformance row refuses the change unless
    ``allow_bootstrap`` waives it.
    """

    def execute(self, *, name: str, allow_bootstrap: bool = False) -> OnboardingResult:
        ...
