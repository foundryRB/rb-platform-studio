"""The stage of an app's delivery, derived from the evidence chain."""

from __future__ import annotations

from enum import StrEnum

__all__ = ["DeliveryStage"]


class DeliveryStage(StrEnum):
    """Where an app sits on its way to serving, read off the chain's links.

    ``serving`` is earned, never assumed: it requires the promotion link ok
    (the deploy branch visibly carries a pinned chart and promoted tags) AND
    the sync link ok (the requested revision applied successfully) AND the
    probe link ok (the hostname answers and workload containers are ready).
    """

    NOT_ONBOARDED = "not_onboarded"
    PR_OPEN = "pr_open"
    AWAITING_FIRST_ARTIFACTS = "awaiting_first_artifacts"
    PROMOTED = "promoted"
    SERVING = "serving"
