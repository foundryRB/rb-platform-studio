"""Response DTO for an upstream refresh."""

from __future__ import annotations

from pydantic import BaseModel

__all__ = ["RefreshResponse"]


class RefreshResponse(BaseModel):
    """Acknowledgement that the checkout was reconciled with upstream."""

    refreshed: bool
