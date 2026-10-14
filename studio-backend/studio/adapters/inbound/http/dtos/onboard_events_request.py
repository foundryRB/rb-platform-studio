"""Request DTO: grant an app access to the shared event bus."""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = ["OnboardEventsRequest"]


class OnboardEventsRequest(BaseModel):
    """The facts an events grant needs: whose it is, which REF-Events domains it
    may publish under, and whether skipped app-side conformance legs are waived
    (the walking-skeleton bootstrap).

    ``domains`` has no default. Publishing is owned per domain, so a grant that
    named none would admit a reader while looking like a producer grant, and one
    defaulting to the app's own name would coin a domain the type registry never
    agreed to.
    """

    name: str = Field(min_length=1, max_length=63)
    domains: list[str] = Field(min_length=1)
    allow_bootstrap: bool = False
