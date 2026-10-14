"""Response DTO for one app's delivery evidence chain."""

from __future__ import annotations

from pydantic import BaseModel

from studio.adapters.inbound.http.dtos.status_link_response import StatusLinkResponse

__all__ = ["AppStatusResponse"]


class AppStatusResponse(BaseModel):
    """The delivery evidence chain of one app, typed link by link.

    ``stage`` is one of not_onboarded, pr_open, awaiting_first_artifacts,
    promoted, serving; serving requires promotion, sync and probe links ok.
    ``sync`` compares the primary Application applied revision and operation
    with the requested deploy head. ``probe`` retains HTTP and workload facts;
    unknown workload proof keeps it skipped. ``chart`` compares effective
    published renders and is advisory.
    ``summary`` names the stage and the first link that is not ok, in chain
    order. ``grant_drift`` reports whether each capability grant on the branch
    still matches what its canonical template renders, which is advisory: it
    names a hand edit rather than refusing anything.
    ``credentials`` reports whether every platform-minted credential
    the app's chart names has the install grant that mints it; it sits outside
    the stage derivation, explaining a hostname that does not answer.
    ``smoke`` reports the app's in-cluster deployed-smoke verdict, read off
    the platform's smoke reporter at the docs host (ADR-047); advisory, and
    skipped for an app that has not adopted the contract.
    """

    name: str
    stage: str
    summary: str
    onboarded: StatusLinkResponse
    onboarding_pr: StatusLinkResponse
    app_repo: StatusLinkResponse
    ci: StatusLinkResponse
    promotion: StatusLinkResponse
    credentials: StatusLinkResponse
    grant_drift: StatusLinkResponse
    probe: StatusLinkResponse
    smoke: StatusLinkResponse
    identity_caveat: StatusLinkResponse
    sync: StatusLinkResponse
    chart: StatusLinkResponse
