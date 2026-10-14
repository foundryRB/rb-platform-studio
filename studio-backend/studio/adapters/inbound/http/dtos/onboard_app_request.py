"""Request DTO for app onboarding."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

__all__ = ["OnboardAppRequest"]


class OnboardAppRequest(BaseModel):
    """The operator-facing facts an app onboarding needs.

    ``role`` is the manifest list the entry lands in (ADR-032): ``parts`` for
    the apps the Foundry depends on, ``output`` (the default) for the apps it
    built and runs. ``image_components`` names the app's released images when
    there is more than one (e.g. ``["server", "client", "docs"]``): the
    Application then watches one GHCR package per component
    (``<name>-<component>``) and writes ``<name>.images.<component>.tag``;
    empty means the single-image shape (package ``<name>``,
    ``<name>.image.tag``). ``repo`` is the app's repository under the org, the
    one thing the rendered Application's ``repoURL`` points at; empty defaults
    to ``name``, the same string for most apps. ``name`` is the fleet name
    (namespace, hostname label, chart, GHCR packages), so an app whose
    repository is named differently from itself names both.
    ``allow_bootstrap`` waives the strict admission on
    skipped app-side conformance legs (the deliberate walking-skeleton
    bootstrap, recorded in the PR body).
    """

    name: str = Field(min_length=1, max_length=63)
    display_name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    icon: str = Field(min_length=1)
    expose_mcp: bool = False
    role: Literal["parts", "output"] = "output"
    image_components: tuple[str, ...] = ()
    repo: str = ""
    allow_bootstrap: bool = False
