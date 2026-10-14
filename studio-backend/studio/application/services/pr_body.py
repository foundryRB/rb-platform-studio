"""Shared markdown fragments for onboarding pull-request bodies."""

from __future__ import annotations

from studio.domain.model.conformance_report import ConformanceReport
from studio.domain.model.test_outcome import TestOutcome
from studio.domain.services.credential_demand import DEMAND_GRANT_ROW

__all__ = [
    "advisory_section",
    "bootstrap_waiver_section",
    "changed_files_section",
    "conformance_section",
    "delivery_section",
]

_DELIVERY_PREFIX = "install/delivery::"


def conformance_section(baseline: ConformanceReport, report: ConformanceReport) -> str:
    """The gate evidence: baseline (the deploy branch) vs this branch, and the verdict."""
    lines = [
        "### Conformance",
        "",
        "| | deploy branch (baseline) | this branch |",
        "|---|---|---|",
        f"| passed | {baseline.passed} | {report.passed} |",
        f"| failed | {baseline.failed} | {report.failed} |",
        f"| skipped | {baseline.skipped} | {report.skipped} |",
        "",
        "Gate: this branch introduces no conformance failure that the deploy "
        "branch does not already have.",
    ]
    return "\n".join(lines)


def changed_files_section(changed: tuple[str, ...]) -> str:
    """The exact file set the branch carries."""
    entries = "\n".join(f"- `{path}`" for path in changed)
    return f"### Files\n\n{entries}"


def delivery_section(app: str, report: ConformanceReport) -> str:
    """The app's delivery-pipeline rows, with every unverified leg named.

    The gate blocks a delivery row that is verifiably wrong, but a row whose
    team-owned leg cannot be read yet (most commonly the deploy branch, stood
    up only after the merge) reports skipped - and a skipped row must read as
    a named warning in the PR, never blend into a green count. Empty when the
    report carries no delivery rows for the app (stubbed runs)."""
    rows = [r for r in report.for_app(app) if r.node_id.startswith(_DELIVERY_PREFIX)]
    if not rows:
        return ""
    lines = ["### Delivery pipeline", ""]
    lines += [f"- `{row.node_id}` {row.outcome.value}" for row in rows]
    if any(row.outcome is TestOutcome.SKIPPED for row in rows):
        lines += [
            "",
            "A skipped row is a named warning, not a pass: that leg of the "
            "delivery pipeline could not be read at onboarding time "
            "(INT-FOUNDRY-013/020). `run_conformance` must report every "
            "`install/delivery::` row for the app passed before it counts "
            "as shipping.",
        ]
    return "\n".join(lines)


def advisory_section(app: str, report: ConformanceReport) -> str:
    """The advisory rows the gate reported without refusing on.

    The gate admits these deliberately (ADVISORY_ROWS: the state they name is
    only resolvable by a later onboarding), which is exactly why a failing one
    must read as a named warning here rather than blend into the failed count
    above. Empty when every advisory row for the app is clean.
    """
    rows = [
        r
        for r in report.for_app(app)
        if r.node_id.startswith(DEMAND_GRANT_ROW)
        and r.outcome in (TestOutcome.FAILED, TestOutcome.ERROR)
    ]
    if not rows:
        return ""
    lines = ["### Advisory", ""]
    lines += [f"- `{row.node_id}` {row.outcome.value}" for row in rows]
    lines += [
        "",
        "The gate reports this row without refusing on it: the grant it asks "
        "for is rendered into `teams/<app>/`, which the app's own onboarding "
        "must create first, so admitting on it would deadlock the ordering. "
        "It is real all the same - a chart naming a platform-minted credential "
        "no grant mints leaves its pod in `CreateContainerConfigError` "
        "(INT-GRANT-004). Run `foundry-onboard-keycloak` or "
        "`foundry-onboard-database` for the missing grant after this merges.",
    ]
    return "\n".join(lines)


def bootstrap_waiver_section(skipped: tuple[str, ...]) -> str:
    """The waiver record: the trail shows the skips were admitted deliberately.

    Strict admission refuses skipped app-side legs by default; when the caller
    waives that with allow_bootstrap (the walking-skeleton bootstrap), the PR
    body names the waiver and every leg it admitted unverified.
    """
    lines = [
        "### Bootstrap waiver",
        "",
        "bootstrap waiver: app-side conformance legs skipped by explicit "
        "allow_bootstrap (the deliberate walking-skeleton bootstrap).",
        "",
    ]
    lines += [f"- `{node_id}` skipped" for node_id in skipped]
    return "\n".join(lines)
