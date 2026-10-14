"""Response DTO for a cancelled change branch."""

from __future__ import annotations

from pydantic import BaseModel

from studio.adapters.inbound.http.dtos.pr_info_response import PrInfoResponse

__all__ = ["CancelledChangeResponse"]


class CancelledChangeResponse(BaseModel):
    """What the cancel found and what it removed.

    ``deleted`` is false when the remote already carried no such branch: the
    verb is idempotent, so a repeat reports a clear remote rather than
    failing. ``prs`` carries every pull request that ever referenced the
    branch, and is empty for the orphan case the verb exists for.
    """

    branch: str
    deleted: bool
    prs: list[PrInfoResponse]
