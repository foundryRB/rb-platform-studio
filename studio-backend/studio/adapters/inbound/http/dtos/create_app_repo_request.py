"""Request DTO for templated app-repo creation."""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = ["CreateAppRepoRequest"]


class CreateAppRepoRequest(BaseModel):
    """The facts a walking-skeleton repo is rendered from.

    ``name`` is the fleet name: the chart, the GHCR package prefix, and later
    the namespace and hostname. ``repo`` is the repository to create it in,
    a separate fact (INT-SKELETON-001) that defaults to the name - an
    organisation shared with other work prefixes its repositories while its
    apps keep their own names, and without this the two could only ever be the
    same string. ``display_name`` and ``description`` seed the landing page,
    the docs site, and the README, and are re-declared to the onboarding later
    (the manifest stays the single source of the tile facts).
    """

    name: str = Field(min_length=1, max_length=63)
    display_name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    repo: str = Field(default="", max_length=100)
