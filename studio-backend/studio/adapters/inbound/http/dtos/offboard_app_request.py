"""Request DTO for app offboarding."""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = ["OffboardAppRequest"]


class OffboardAppRequest(BaseModel):
    """The one fact an offboarding needs: which app to retire.

    The removal is derived from the record itself (the manifest entry and
    whatever the teams/<app>/ folder holds), so nothing else is declared
    here. The merge also prunes the app's namespace, deleting every volume
    its own chart claims, with its data on a Delete reclaim policy, so those
    volumes are copied out before the call. Stateful grants are never
    dropped by the offboarding: the pull request enumerates them for an
    explicit disposition decision.
    """

    name: str = Field(min_length=1, max_length=63)
