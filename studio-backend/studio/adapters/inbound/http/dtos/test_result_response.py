"""Response DTO for one conformance test row."""

from __future__ import annotations

from pydantic import BaseModel

__all__ = ["TestResultResponse"]


class TestResultResponse(BaseModel):
    """One pytest node id, its verdict, and what the node id cannot say.

    ``detail`` names the concrete artifact a row judged (the repository that
    would not answer, say); rows whose node id is self-explanatory leave it
    empty.
    """

    node_id: str
    outcome: str
    detail: str = ""
