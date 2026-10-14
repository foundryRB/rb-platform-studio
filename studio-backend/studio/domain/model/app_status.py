"""The delivery evidence chain of one app, as one typed record."""

from __future__ import annotations

from dataclasses import dataclass

from studio.domain.model.delivery_stage import DeliveryStage
from studio.domain.model.link_status import LinkStatus
from studio.domain.model.status_link import StatusLink

__all__ = ["AppStatus"]


@dataclass(frozen=True)
class AppStatus:
    """Every link of one app's delivery evidence chain, plus the derived stage.

    The chain a delivery run must prove: onboarded (manifest entry and teams
    folder), onboarding_pr (an admission PR still open), app_repo (the
    app-side conformance legs), ci (the latest completed run on the default
    branch), promotion (the deploy branch's pinned chart and promoted tags),
    sync (the primary Application revision and operation), chart (effective
    published render comparison, advisory),
    credentials (every platform-minted credential the chart names having the
    grant that mints it), probe (the hostname and workload observations), smoke (the app's
    in-cluster deployed-smoke verdict, read off the platform's smoke reporter
    at the docs host, ADR-047), and identity_caveat (the OIDC round-trip no
    edge probe can prove). ``summary`` is the one-line reading: the stage and
    the first link that is not ok, in chain order.

    ``credentials`` sits immediately before ``probe`` because it is the
    standing explanation for a hostname that does not answer: a chart naming
    a credential no grant mints leaves its pod in
    ``CreateContainerConfigError``, so a chain that reads probe-failed alone
    blames the edge for a cause that is visible in git.
    """

    app: str
    onboarded: StatusLink
    onboarding_pr: StatusLink
    app_repo: StatusLink
    ci: StatusLink
    promotion: StatusLink
    credentials: StatusLink
    grant_drift: StatusLink
    probe: StatusLink
    smoke: StatusLink
    identity_caveat: StatusLink
    stage: DeliveryStage
    summary: str
    sync: StatusLink = StatusLink(LinkStatus.SKIPPED, "Application sync unknown")
    chart: StatusLink = StatusLink(LinkStatus.SKIPPED, "Rendered chart comparison unknown")

    def links(self) -> tuple[tuple[str, StatusLink], ...]:
        """The links in chain order, named; the order summaries read them in."""
        return (
            ("onboarded", self.onboarded),
            ("onboarding_pr", self.onboarding_pr),
            ("app_repo", self.app_repo),
            ("ci", self.ci),
            ("promotion", self.promotion),
            ("sync", self.sync),
            ("chart", self.chart),
            ("credentials", self.credentials),
            ("probe", self.probe),
            ("smoke", self.smoke),
            ("identity_caveat", self.identity_caveat),
        )
