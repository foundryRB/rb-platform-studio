"""Inbound port: grant an onboarded app access to the shared event bus."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from studio.domain.model.onboarding_result import OnboardingResult

__all__ = ["OnboardEventsPort"]


@runtime_checkable
class OnboardEventsPort(Protocol):
    """Prepare the install-side event-bus grant, conformance-gated.

    Renders the app's key generator and its signing Job from the studio's
    canonical template into the app's team folder (per concern file), on the
    same PR-or-working-tree path as app onboarding, with the same strict
    admission: a skipped app-side conformance row refuses the change unless
    ``allow_bootstrap`` waives it.

    ``domains`` are the REF-Events domains the app owns and may publish under.
    At least one is required: publishing is owned per domain, and a grant that
    named none would admit a reader while looking like a producer grant.
    """

    def execute(
        self,
        *,
        name: str,
        domains: tuple[str, ...] | list[str],
        allow_bootstrap: bool = False,
    ) -> OnboardingResult:
        ...
