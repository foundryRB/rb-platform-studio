"""Inbound port: reconcile an onboarded app's rendered folder with its declaration."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from studio.domain.model.onboarding_result import OnboardingResult

__all__ = ["ReconcileAppPort"]


@runtime_checkable
class ReconcileAppPort(Protocol):
    """Re-render one onboarded app's teams/<app>/ skeleton, conformance-gated.

    The onboarding writes the standing configuration the platform actors read
    (the Application pointer, the Image Updater aliases, the Gateway); nothing
    re-writes it afterwards, so when the app's shape changes - it releases
    more images, the canonical templates themselves evolved - the folder
    drifts from both the app and canon. Reconcile is the supported repair: it
    re-renders the five skeleton files from the CURRENT canonical templates
    and a FRESH ``image_components`` declaration, refreshes the manifest
    entry (writing the description in, so the manifest stays the single
    source of the tile facts), and leaves every grant file (jobs,
    serviceaccounts, realm config) untouched. The act gate is strict: the
    cross-repo agreement rows (bindings against the deploy values, aliases
    against the released set, the docs image) run here, the one moment they
    are resolvable by the caller. Ships as a pull request against the deploy
    branch, admitted by the platform repo's CI (ADR-036), exactly like the
    onboarding it repairs.
    """

    def execute(
        self,
        *,
        name: str,
        image_components: tuple[str, ...] = (),
        description: str = "",
        repo: str = "",
        allow_bootstrap: bool = False,
    ) -> OnboardingResult:
        ...
