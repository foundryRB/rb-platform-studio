"""Request DTO for app reconciliation."""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = ["ReconcileAppRequest"]


class ReconcileAppRequest(BaseModel):
    """The fresh declaration a reconcile re-renders the team folder against.

    ``image_components`` is the accountable re-declaration of the app's
    released images (empty means the single-image shape), the one input that
    usually motivates the reconcile; ``description`` refreshes the manifest's
    tile description when given (empty keeps the current one); ``repo``
    overrides the repository the Application points at and the manifest
    entry records (empty keeps the entry's, else the Application's).
    Display, icon, role, and the mcp flag are read from the existing manifest
    entry: reconcile repairs the rendered folder, it does not rebrand the app.
    """

    name: str = Field(min_length=1, max_length=63)
    image_components: tuple[str, ...] = ()
    description: str = ""
    repo: str = ""
    allow_bootstrap: bool = False
