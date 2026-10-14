"""Request DTO for re-rendering an app's identity (Keycloak realm) grant."""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = ["ReconcileIdentityRequest"]


class ReconcileIdentityRequest(BaseModel):
    """The facts a realm re-render needs: whose realm, and whether skipped
    app-side conformance legs are waived (the walking-skeleton bootstrap).

    Nothing else is taken: the declaration a re-render applies is the install's
    own (``defaultBrokers`` and the login theme on its deploy branch), never a
    caller's, so the realm can only ever be brought to what the branch says.
    """

    name: str = Field(min_length=1, max_length=63)
    allow_bootstrap: bool = False
