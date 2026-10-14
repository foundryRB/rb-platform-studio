"""Inbound port: onboard an app onto the install."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from studio.domain.model.onboarding_result import OnboardingResult

__all__ = ["OnboardAppPort"]


@runtime_checkable
class OnboardAppPort(Protocol):
    """Prepare the install-side onboarding of one app, conformance-gated.

    Adds the app's entry to the install manifest (foundry.yaml, under its
    role: parts or output, default output), renders its teams/<app>/ folder
    from the studio's canonical templates, and gates the whole change on the
    install conformance checks. ``image_components`` names the app's released
    images when there is more than one: the rendered Application then carries
    one Image Updater alias per component (package ``<name>-<component>``,
    values ``<name>.images.<component>``); empty means the single-image shape
    (package ``<name>``, values ``<name>.image``). ``repo`` is the app's
    repository under the org, the one thing the rendered Application's
    ``repoURL`` points at; it defaults to ``name``, the same string for most
    apps. ``name`` is the fleet name (namespace, hostname label, chart, GHCR
    packages), so an app whose repository is named differently from itself
    names both. Admission is strict on the
    app's own delivery legs: a skipped app-side conformance row refuses the
    change unless ``allow_bootstrap`` waives it (the deliberate
    walking-skeleton bootstrap, recorded in the PR body). The change ships as
    a pull request against the deploy branch (deployed) or stays in the
    working tree (local run); it never lands on the deploy branch directly.
    """

    def execute(
        self,
        *,
        name: str,
        display_name: str,
        description: str,
        icon: str,
        expose_mcp: bool,
        role: str = "output",
        image_components: tuple[str, ...] = (),
        repo: str = "",
        allow_bootstrap: bool = False,
    ) -> OnboardingResult:
        ...
