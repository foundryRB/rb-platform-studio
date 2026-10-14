"""Inbound port: re-render an app's existing Keycloak realm grant."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from studio.domain.model.onboarding_result import OnboardingResult

__all__ = ["ReconcileIdentityPort"]


@runtime_checkable
class ReconcileIdentityPort(Protocol):
    """Re-render one granted realm from the current template and declaration,
    conformance-gated.

    The day-2 verb for a realm (ADR-045): a realm carries what it was rendered
    with until it is reconciled, and until now nothing reconciled it -
    ``onboard_identity`` refuses an app whose realm exists and ``reconcile_app``
    leaves every grant file alone. This re-renders the realm ConfigMap and its
    provisioning Job from the CURRENT canonical template and the install's
    CURRENT declaration (``defaultBrokers``, the login theme), replacing them in
    place in the app's team folder: the admitted users are carried across, the
    app-owned credential and its generator, the client, the host and every
    other grant are untouched, and the rendered documents are byte-identical to
    a fresh onboarding's for the same declaration. Refuses before any branch is
    prepared when the branch already carries that render (nothing to
    reconcile), and refuses an app that holds no realm. Ships as a pull
    request against the deploy branch on the same gate-validate-rollback path
    as the onboarding, with the same strict admission on skipped app-side
    legs, which ``allow_bootstrap`` waives.
    """

    def execute(self, *, name: str, allow_bootstrap: bool = False) -> OnboardingResult:
        ...
