"""One commit of an app repo branch, as the repo host reports it."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["CommitInfo"]


@dataclass(frozen=True)
class CommitInfo:
    """Identity and timing of one commit (e.g. the Image Updater write-back
    that last touched the deploy branch's prod values)."""

    sha: str
    message: str
    committed_at: str
