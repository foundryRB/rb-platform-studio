"""One conformance test node and its outcome."""

from __future__ import annotations

from dataclasses import dataclass

from studio.domain.model.test_outcome import TestOutcome

__all__ = ["TestResult"]


@dataclass(frozen=True)
class TestResult:
    """A single pytest node id with the verdict it reported.

    ``detail`` carries what the node id alone cannot say: the concrete artifact
    a row judged and why it landed where it did (the repo URL that could not be
    read, say). Rows whose node id is self-explanatory leave it empty.
    """

    node_id: str
    outcome: TestOutcome
    detail: str = ""
