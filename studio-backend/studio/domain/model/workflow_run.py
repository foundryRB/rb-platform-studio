"""One completed CI workflow run of an app repo."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["WorkflowRun"]


@dataclass(frozen=True)
class WorkflowRun:
    """The latest completed run on a branch, as the repo host reports it.

    A ``success`` conclusion of the shared reusable workflow is the chain's
    "CI green + artifacts published" proxy: that workflow's green path is the
    one that pushes the app image, the docs image, and the chart to GHCR.
    """

    name: str
    conclusion: str
    url: str
    completed_at: str
