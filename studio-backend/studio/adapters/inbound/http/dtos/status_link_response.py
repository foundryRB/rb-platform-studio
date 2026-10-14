"""Response DTO for one evidence-chain link."""

from __future__ import annotations

from pydantic import BaseModel

__all__ = ["StatusLinkResponse"]


class StatusLinkResponse(BaseModel):
    """One link of the delivery evidence chain: its verdict and detail.

    ``status`` is ok, failed, or skipped; a skipped link's detail always
    names the reason it could not be evaluated.
    """

    status: str
    detail: str
