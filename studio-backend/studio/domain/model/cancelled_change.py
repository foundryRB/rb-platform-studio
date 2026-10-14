"""The outcome of cancelling a wedged change branch."""

from __future__ import annotations

from dataclasses import dataclass

from studio.domain.model.pr_info import PrInfo

__all__ = ["CancelledChange"]


@dataclass(frozen=True)
class CancelledChange:
    """What the cancel verb found and what it removed.

    ``deleted`` is false when the remote already carried no such branch: the
    verb is idempotent, so a second run reports a clean remote rather than
    failing. ``prs`` carries every pull request that ever referenced the
    branch, which is empty for the orphan case the verb exists for.
    """

    branch: str
    deleted: bool
    prs: tuple[PrInfo, ...]
