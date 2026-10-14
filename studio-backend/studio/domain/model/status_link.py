"""One typed link of the delivery evidence chain."""

from __future__ import annotations

from dataclasses import dataclass

from studio.domain.model.link_status import LinkStatus

__all__ = ["StatusLink"]


@dataclass(frozen=True)
class StatusLink:
    """A single evidence-chain observation: its verdict and what was seen.

    The detail carries the observed facts (a hostname, a run conclusion, a
    pinned version, a status code with latency) so the caller reads evidence,
    not just a verdict; a skipped link's detail names the reason it could not
    be evaluated.
    """

    status: LinkStatus
    detail: str
