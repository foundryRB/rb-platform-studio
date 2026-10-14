"""ConformanceRunner over the install's working tree (the candidate state).

The platform's own conformance suite reads installed state from the committed
deploy-* branch refs (`git show`), so it cannot see a candidate onboarding
that exists only as uncommitted working-tree edits. This runner adapts the
suite's per-install checks to the working tree itself, so the gate validates
exactly the state the pull request would ship: the manifest <-> teams-folder
bijection (INT-FOUNDRY-001), entry shape, the derived MCP endpoints
(INT-FOUNDRY-028), the ArgoCD Application wiring (INT-FOUNDRY-011/021),
database-grant isolation, the Image Updater bindings (coherent in
themselves; when an AppRepoSource is wired and the app's deploy values are
readable, matching those values in both directions; and, when the app
repo's compose is readable, watching exactly the released set - the
compose build: services plus the docs image), the team-side delivery
pipeline (INT-FOUNDRY-013/020: the CI caller and the deploy branch, read
off the repo host with no clone), and the credential demand-grant
cross-check (INT-GRANT-004: a chart naming keycloak-<app>,
pg-app-<app> or nats-<app> has the grant in teams/<app>/ that mints it). A row whose
team-owned leg cannot be read reports skipped, never passed. The gate
semantics stay a baseline diff in GatedChange: a change may not introduce
a failure the deploy branch does not already have, save the advisory rows
it reports without refusing on.

Two venues, one runner (``act_rows``). The standing venue (run_conformance,
conformance_report, the status read's app_repo link) judges only what the
install itself owns: an app team growing its released images must never
flip the install report red, because the interim state between an app-side
change and its reconcile_app is intended, not broken. The act venue (the
gate inside onboard_app / reconcile_app / offboard_app) is the one moment
the cross-repo agreement is resolvable by the caller, so only there do the
promotion agreement rows run - image-updater-promotes (the bindings against
the deploy values they write) and image-updater-released-set (the aliases
against what the app repo's CI actually publishes) - plus the docs-image
requirement (every onboarded app ships its documentation image; no docs,
no onboard). image-updater-coherent stays standing: it reads only the
annotations the install branch itself carries.
"""

from __future__ import annotations

import re
import time
import traceback
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

from studio.application.ports.outbound.app_repo_source import AppRepoSource
from studio.domain.exceptions.unverified_legs_error import APP_REPO_ROW
from studio.domain.model.conformance_report import ConformanceReport
from studio.domain.model.test_outcome import TestOutcome
from studio.domain.model.test_result import TestResult
from studio.domain.services.credential_demand import (
    DEMAND_GRANT_ROW,
    credential_mismatches,
    effective_values,
    ungranted_credential_demands,
)
from studio.domain.services.environments import declared_environments
from studio.domain.services.image_promotion import (
    ANNOTATION_PREFIX,
    image_updater_problems,
    released_packages,
    released_set_problems,
    unpromoted_bindings,
)
from studio.domain.services.install_symmetry import symmetry_problems
from studio.domain.services.team_documents import (
    database_job_is_isolation_clean,
    homepage_group_for_role,
)
from studio.logging import get_logger

__all__ = ["InstallConformanceRunner"]

logger = get_logger(__name__)

_DNS_LABEL = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
_REPO_TTL_SECONDS = 300
_ZONE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")

# The env-config filenames INT-FOUNDRY-020 requires per declared environment
# on every install deploy branch (the platform's ADR-025/032): the values plus
# the Chart.yaml pinning the published chart. The environment set itself is
# the manifest's declaration, so the expected file set derives per install.
_ENV_FILES = ("values.yaml", "Chart.yaml")

# A branch path shaped like env config: <env>/values.yaml or <env>/Chart.yaml.
# Used for the reverse leg - an env-config folder the declaration does not
# carry is a dormant environment the install no longer owns.
_ENV_CONFIG_PATH = re.compile(r"^(?P<env>[^/]+)/(?:values|Chart)\.yaml$")

# Fan-out width for the repo-host prefetch. The app-side reads are independent
# per app and dominated by network latency, so issuing them concurrently is what
# makes a cold run fast; the cap holds the burst inside GitHub's secondary-limit
# guidance. The hourly call budget is untouched - the fan-out issues the same
# reads, just not one at a time.
#
# 16 is where the knee is, measured cold over the chaos install (27 apps, 262
# rows): serial 111s, 8 workers 17s, 16 workers 10s, 24 workers 9.6s. Past 16 the
# run is latency-bound on the slowest single repo, so more concurrency buys ~6%
# for 50% more burst.
_PREFETCH_WORKERS = 16

# The files the app-side legs read off the repo's DEFAULT branch, listed here
# only so the prefetch can warm them. The check loop stays the single authority
# on what each one means; a path missing here costs one serial read, never a
# wrong row.
_DEFAULT_BRANCH_FILES = (".github/workflows/build.yml", "k8s/values.yaml")
# The act venue reads two more: the docs image and the released set.
_ACT_BRANCH_FILES = ("devops/docker-compose.yml", "docs/Dockerfile")


def _unread_detail(repo_url: str, branch: str, path: str) -> str:
    """The skip detail for a file read that came back empty while the branch
    listing does not confirm the file absent."""
    return (
        f"{repo_url}: {path} on {branch} could not be read and the branch "
        "listing does not show it absent"
    )


def _gateway_hostname(docs: list[dict]) -> str:
    """The hostname the app's Gateway listener declares, "" when there is none."""
    for doc in docs:
        if doc.get("kind") == "Gateway":
            listeners = (doc.get("spec") or {}).get("listeners") or []
            if listeners:
                return str(listeners[0].get("hostname") or "")
    return ""


class InstallConformanceRunner:
    """Runs the per-install checks against the working tree and reports
    per-check rows a gate diff can compare (per-app rows carry [<app>])."""

    def __init__(
        self,
        platform_root: Path,
        app_repo: AppRepoSource | None = None,
        act_rows: bool = False,
    ) -> None:
        self._root = platform_root
        self._app_repo = app_repo
        # act_rows widens the row set to the act-only cross-repo agreement
        # rows (promotes, released-set, docs-image). The standing venue never
        # emits them, so an app-side change can never fail the install report;
        # the act venue emits them because the act is where they are resolvable.
        self._act_rows = act_rows
        # Repo-host reads are cached briefly across runs: the gate diffs a
        # baseline run against a candidate run seconds apart, and a fetch that
        # fails in one but succeeds in the other would turn a pre-existing
        # app-repo-row failure into a "new" one, refusing an unrelated change.
        # The TTL keeps a long-lived studio from serving stale facts forever.
        self._repo_cache: dict[tuple[str, ...], tuple[float, object]] = {}

    def run(self) -> ConformanceReport:
        try:
            results = self._checks()
        except Exception:
            output = traceback.format_exc()
            logger.warning("Install conformance failed to run:\n%s", output)
            return ConformanceReport(exit_code=2, results=(), output=output[-8000:])
        failed = [
            r for r in results if r.outcome in (TestOutcome.FAILED, TestOutcome.ERROR)
        ]
        exit_code = 1 if failed else 0
        # A row's detail rides in the output, not just on the result object: the
        # gate's rejection message prints new_failures plus this text, so a
        # detail dropped here leaves a caller with a node ID and nothing else to
        # act on - the mismatch is already computed, so withholding it just
        # sends the caller off to rediscover it by hand.
        output = "\n".join(
            f"{r.node_id} {r.outcome.value.upper()}" + (f": {r.detail}" if r.detail else "")
            for r in results
        )
        logger.info("Install conformance exit %d (%d check rows)", exit_code, len(results))
        return ConformanceReport(exit_code=exit_code, results=tuple(results), output=output[-8000:])

    def _checks(self) -> list[TestResult]:
        manifest = self._yaml("foundry.yaml")
        values = self._yaml("values.yaml")
        zone = str(values.get("zone") or "")
        install = str(manifest.get("install") or "")
        environments = declared_environments(manifest)
        entries = [
            (item, role)
            for role in ("parts", "output")
            for item in (manifest.get(role) or [])
            if isinstance(item, dict)
        ]
        names = [str(item.get("name") or "") for item, _ in entries]
        folders = self._team_folders()
        # Warm every app-side read concurrently before the sequential checks
        # consume them; see _prefetch.
        self._prefetch([name for name in names if name in folders])

        results: list[TestResult] = []

        def check(node_id: str, ok: bool, detail: str = "") -> None:
            results.append(
                TestResult(
                    node_id=node_id,
                    outcome=TestOutcome.PASSED if ok else TestOutcome.FAILED,
                    detail="" if ok else detail,
                )
            )

        def skip(node_id: str, detail: str = "") -> None:
            results.append(
                TestResult(node_id=node_id, outcome=TestOutcome.SKIPPED, detail=detail)
            )

        # values.yaml declares the zone hostnames and MCP endpoints derive from.
        check("install/values::zone-declared", bool(_ZONE.match(zone)))

        # INT-FOUNDRY-001: manifest (parts + output) <-> teams/ folders, in bijection.
        duplicates = {n for n in names if names.count(n) > 1}
        check(
            "install/parity::manifest-teams-bijection",
            not duplicates and set(names) == set(folders),
        )

        for (item, role), name in zip(entries, names, strict=True):
            docs = self._team_docs(name)
            # Entry shape: a DNS-label name plus the display facts every
            # manifest-derived view renders from.
            check(
                f"install/manifest::entry-shape[{name}]",
                bool(_DNS_LABEL.match(name))
                and bool(str(item.get("display") or "").strip())
                and bool(str(item.get("icon") or "").strip()),
            )
            # An onboarded app's tile renders from its manifest entry, so a
            # rendered skeleton carries no group annotation and this row holds
            # vacuously. A folder authored before the manifest became the tile's
            # source may still carry one, and homepage discovers annotated routes
            # cluster-wide: a group disagreeing with the role (parts -> Foundry,
            # output -> Apps) seats the app under a heading every
            # manifest-derived view denies.
            route_groups = {
                ((d.get("metadata") or {}).get("annotations") or {}).get("gethomepage.dev/group")
                for d in docs
                if d.get("kind") == "HTTPRoute"
            }
            route_groups.discard(None)
            check(
                f"install/homepage::group-matches-role[{name}]",
                not route_groups or route_groups == {homepage_group_for_role(role)},
            )
            # INT-FOUNDRY-028 (static half): an mcp: true entry derives a
            # well-formed https://<host>/mcp endpoint inside the install zone,
            # the host read from the app's Gateway listener because external-dns
            # publishes the record from it; <name>.<zone> is the fallback only
            # for a flagged entry whose folder carries no listener to read.
            if item.get("mcp") is True:
                mcp_host = _gateway_hostname(docs) or f"{name}.{zone}"
                check(
                    f"install/mcp::derived-endpoint[{name}]",
                    bool(_DNS_LABEL.match(name))
                    and bool(_ZONE.match(mcp_host))
                    and mcp_host.endswith(f".{zone}"),
                )
            if name not in folders:
                continue  # the bijection row already fails; no folder to inspect
            # INT-FOUNDRY-011/021: an ArgoCD Application targeting the app repo's
            # per-install deploy branch (deploy-<install>), never the in-repo walking
            # skeleton. Matches INT-FOUNDRY-021 (test_app_delivery), strict on the
            # per-install branch now the migration off the single `deploy` is done.
            applications = [d for d in docs if d.get("kind") == "Application"]
            check(
                f"install/delivery::argocd-application[{name}]",
                bool(applications)
                and all(
                    ((a.get("spec") or {}).get("source") or {}).get("targetRevision")
                    == f"deploy-{install}"
                    and not str(
                        ((a.get("spec") or {}).get("source") or {}).get("path", "")
                    ).startswith("apps/")
                    for a in applications
                ),
            )
            # INT-FOUNDRY-013 / INT-FOUNDRY-020: the team-side delivery
            # pipeline, judged over the repo host (no clone) so the gate sees
            # it at onboarding time; the platform's own copies of these rules
            # (test_repo_conformance) are unreachable exactly then - the in-CI
            # audit runs only in repos already calling the shared workflow,
            # and the platform-side run needs a sibling clone. A leg that is
            # readable and wrong fails (a new per-app row, so the gate refuses
            # the onboarding PR); a leg that cannot be read (repo not granted
            # to the token, deploy branch not stood up yet - the runbook
            # stands it up after the merge) reports skipped, never passed,
            # and the onboarding PR body names every skipped row.
            delivery_source = (
                ((applications[0].get("spec") or {}).get("source") or {})
                if applications
                else {}
            )
            repo_url = str(delivery_source.get("repoURL") or "")
            repo_owner = re.search(r"github\.com[:/]([^/]+)/", repo_url)
            default = self._default_branch(repo_url) if repo_url else None
            # The repository every leg below reads through, judged on its own
            # row so its state is said once instead of surfacing as four
            # skipped legs that each name a different artifact to stand up.
            # A host that answers "not there for this caller" is a definite
            # fact about the repo and reports red; anything that proves
            # nothing (no source wired, host unreachable, credentials
            # rejected) reports skipped, so a greenfield onboarding is never
            # refused over an artifact the runbook stands up after the merge.
            visible = self._repo_exists(repo_url) if repo_url else None
            if visible is None:
                skip(
                    f"{APP_REPO_ROW}[{name}]",
                    detail=(
                        f"{repo_url} could not be reached"
                        if repo_url
                        else "the Application names no repoURL, so no app-side leg can be read"
                    ),
                )
            else:
                check(
                    f"{APP_REPO_ROW}[{name}]",
                    visible,
                    detail=(
                        f"{repo_url} is not there for the studio: no such repository under "
                        f"that owner, or the token is not granted it. The app is named "
                        f"{name!r}; onboard with an explicit repo when the repository is "
                        "named differently from the app. Every app-side leg below reads "
                        "through this repo, so they report skipped until it resolves."
                    ),
                )
            if default is None or repo_owner is None:
                skip(f"install/delivery::ci-caller[{name}]")
            else:
                # INT-FOUNDRY-013: without the shared CI caller no image or chart
                # reaches GHCR. The CI repository's name is the organisation's, so
                # only the owner and the workflow path are pinned.
                workflow_path = ".github/workflows/build.yml"
                workflow = self._file_text(repo_url, default, workflow_path)
                if workflow is None and self._unanswered(repo_url, default, workflow_path):
                    skip(
                        f"install/delivery::ci-caller[{name}]",
                        detail=_unread_detail(repo_url, default, workflow_path),
                    )
                else:
                    check(
                        f"install/delivery::ci-caller[{name}]",
                        workflow is not None
                        and re.search(
                            r"uses:\s+"
                            + re.escape(repo_owner.group(1))
                            + r"/[^/\s]+/\.github/workflows/build\.yml@",
                            workflow,
                        )
                        is not None,
                    )
            deploy_branch = str(delivery_source.get("targetRevision") or "")
            branch_files = (
                self._branch_paths(repo_url, deploy_branch)
                if repo_url and deploy_branch
                else None
            )
            if branch_files is None:
                skip(f"install/delivery::deploy-branch[{name}]")
            else:
                # INT-FOUNDRY-020: the deploy-<install> branch the rendered
                # Application reconciles carries exactly the declared
                # environments' config - one folder per declared environment
                # (a branch without one gives ArgoCD nothing to deliver), and
                # no env-config folder outside the declaration (a dormant
                # environment nothing reconciles and nothing may write).
                expected = {f"{env}/{f}" for env in environments for f in _ENV_FILES}
                extra = sorted(
                    {
                        m.group("env")
                        for p in branch_files
                        if (m := _ENV_CONFIG_PATH.match(p))
                    }
                    - set(environments)
                )
                missing = sorted(expected - branch_files)
                check(
                    f"install/delivery::deploy-branch[{name}]",
                    not missing and not extra,
                    detail=(
                        (f"missing declared env config: {missing}; " if missing else "")
                        + (f"env folders outside the declaration: {extra}" if extra else "")
                    ).strip("; ")
                    or None,
                )
            if self._act_rows:
                # The docs requirement, judged only at act time (the standing
                # rule: no docs, no onboard). The docs/Dockerfile on the
                # default branch is the source of the <app>-docs image CI
                # publishes; a repo whose default-branch listing answers
                # without it fails the act, which no allow_bootstrap waives
                # (the waiver admits only skips). An empty read the listing
                # does not confirm as absent reports skipped.
                if default is None:
                    skip(f"install/onboarding::docs-image[{name}]")
                else:
                    docs_path = "docs/Dockerfile"
                    docs_dockerfile = self._file_text(repo_url, default, docs_path)
                    if docs_dockerfile is None and self._unanswered(repo_url, default, docs_path):
                        skip(
                            f"install/onboarding::docs-image[{name}]",
                            detail=_unread_detail(repo_url, default, docs_path),
                        )
                    else:
                        check(
                            f"install/onboarding::docs-image[{name}]",
                            docs_dockerfile is not None,
                            detail=(
                                f"the app repo has no docs/Dockerfile on {default}: every "
                                f"onboarded app ships its documentation image ({name}-docs), "
                                "served under the docs portal at /apps/" + name + ". "
                                "No docs, no onboard."
                            ),
                        )
            # Image Updater bindings (INT-PROMOTE-002): the annotations must be
            # coherent in themselves and - when the app's deploy values are
            # readable - must match them in both directions (every bound tag
            # path exists there; every image tag there is bound). A mismatched
            # binding promotes nothing, with no crash and no red status, so the
            # silent never-promotes state fails here instead. Unreadable deploy
            # values (the team-owned branch may not exist yet) report skipped.
            promoting = next(
                (
                    a
                    for a in applications
                    if f"{ANNOTATION_PREFIX}image-list"
                    in (((a.get("metadata") or {}).get("annotations")) or {})
                ),
                None,
            )
            if promoting is not None:
                annotations = {
                    str(key): str(value)
                    for key, value in (
                        ((promoting.get("metadata") or {}).get("annotations")) or {}
                    ).items()
                }
                app_source = (promoting.get("spec") or {}).get("source") or {}
                owner = re.search(
                    r"github\.com[:/]([^/]+)/", str(app_source.get("repoURL") or "")
                )
                registry_block = self._yaml("values.yaml").get("registry") or {}
                registry_prefix = (
                    f"{registry_block.get('host')}/{registry_block.get('owner')}"
                    if registry_block.get("host") and registry_block.get("owner")
                    else ""
                )
                incoherent = image_updater_problems(
                    app=name,
                    repo_owner=owner.group(1) if owner else "",
                    annotations=annotations,
                    registry=registry_prefix,
                )
                check(
                    f"install/promotion::image-updater-coherent[{name}]",
                    not incoherent,
                    detail="; ".join(incoherent),
                )
                # The promotion agreement rows are act-only: the state they
                # judge (bindings vs the deploy values, aliases vs the
                # released set) is team-caused and only resolvable by an act
                # (reconcile_app), so the standing report never fails on it -
                # the shared ci workflow's conformance job is where the drift
                # bites, on the causer's desk, and the status read keeps
                # reporting the promotion facts as diagnosis.
                if self._act_rows:
                    values = self._deploy_values(app_source)
                    if values is None:
                        skip(f"install/promotion::image-updater-promotes[{name}]")
                    else:
                        unpromoted = unpromoted_bindings(
                            app=name, annotations=annotations, deploy_values=values
                        )
                        check(
                            f"install/promotion::image-updater-promotes[{name}]",
                            not unpromoted,
                            detail="; ".join(unpromoted),
                        )
                    # The released set (INT-PROMOTE-003): the aliases must watch
                    # exactly the images the app repo's CI publishes - the compose
                    # build: services plus the docs image (<app>-docs when
                    # docs/Dockerfile exists). A phantom alias watches a package
                    # CI never publishes, a released image no alias watches never
                    # promotes, and the values-bound legs can agree with either,
                    # so the set mismatch fails here. An unreadable repo or
                    # compose, or an empty docs/Dockerfile read the listing
                    # does not confirm as absent, reports skipped.
                    released = self._released_set(name, app_source)
                    if released is None:
                        skip(f"install/promotion::image-updater-released-set[{name}]")
                    else:
                        mismatched = released_set_problems(
                            annotations=annotations, released=released
                        )
                        # The failure names the derived set and the two files it was
                        # derived from, not just the mismatch: the docs image is
                        # never a compose build: service, so a caller reading the
                        # compose alone under-counts every app that ships docs/ and
                        # has nothing in the row to tell them so.
                        check(
                            f"install/promotion::image-updater-released-set[{name}]",
                            not mismatched,
                            detail="; ".join(
                                (
                                    *mismatched,
                                    "the app repo releases "
                                    f"{', '.join(released) or 'no images at all'} "
                                    "(its devops/docker-compose.yml build: services plus "
                                    "<app>-docs when docs/Dockerfile exists, read off the "
                                    "default branch)",
                                )
                            ),
                        )
            # INT-GRANT-004: the chart and the grant name the same credential,
            # judged in BOTH directions. A chart naming keycloak-<app>,
            # pg-app-<app> or nats-<app> has the grant that mints it; and a grant present in
            # teams/<app>/ is named by the chart. The second direction is the
            # one that catches a substitution: an invented name (knight-fight's
            # knight-fight-oidc) matches no credential, and a check that only
            # matched literals read that absence as nothing to judge and passed
            # green over a pod that never started. Anchoring on the grant - a
            # fact the team folder states - is what closes that.
            # The demand lives in the app repo's own chart values and the grant
            # on the install branch, so this is the one place both halves are
            # readable; an unreadable chart reports skipped. The row is
            # diagnostic, not admission-gating (see GatedChange.ADVISORY_ROWS):
            # the grant it asks for can only be rendered into a teams folder an
            # onboarding has already created.
            chart_values = self._chart_values(delivery_source)
            deploy_values = self._deploy_values(delivery_source)
            missing_values = ", ".join(
                label for label, value in (
                    ("chart values", chart_values), ("deploy values", deploy_values)
                ) if value is None
            )
            if missing_values:
                skip(f"{DEMAND_GRANT_ROW}[{name}]", f"Unreadable {missing_values}")
            else:
                granted = {
                    str((d.get("metadata") or {}).get("name") or "") for d in docs
                }
                # Judged on the effective values: a chart may default a
                # capability off so it still installs standalone and let the
                # deploy branch, where the credential exists, turn it on
                # (shoot4fun). The chart default alone would report that
                # correct, live app as consuming nothing.
                live_values = effective_values(
                    app=name,
                    chart_values=chart_values,
                    deploy_values=deploy_values,
                )
                credential_problems = (
                    *ungranted_credential_demands(
                        app=name, values=live_values, granted=granted
                    ),
                    *credential_mismatches(
                        app=name, values=live_values, granted=granted
                    ),
                )
                check(
                    f"{DEMAND_GRANT_ROW}[{name}]",
                    not credential_problems,
                    detail="; ".join(credential_problems),
                )
            # Per-install symmetry: the hostname the app serves and the realm
            # its OIDC sidecar trusts must be this install's own. The app
            # chart's defaults belong to whichever install it was authored
            # against, so a deploy branch that omits the key inherits a
            # foreign one - the platform stays green while the app serves the
            # wrong zone or crash-loops against the wrong Keycloak, which is
            # exactly how psa inherited chaos (foundry-platform#47). The
            # install-agnostic chart shape (INT-FOUNDRY-046) fails the other
            # way: the chart ships the key empty and guards its HTTPRoute
            # with it, so a branch that never pins it renders no route and no
            # DNS record at all - stage promoted, probe NXDOMAIN, every
            # git-side row green (how proxiverso shipped on chaos). Judged on
            # the effective value (deploy override, else chart default) of
            # every key whose capability the same values leave live, so the
            # dormant auth block a scaffolded repo ships is not held to an
            # issuer its absent sidecar would read; an unreadable chart or
            # deploy branch reports skipped, never passed.
            if missing_values:
                skip(
                    f"install/parity::per-install-hostnames[{name}]",
                    f"Unreadable {missing_values}",
                )
            else:
                asymmetric = symmetry_problems(
                    app=name,
                    zone=zone,
                    deploy_values=deploy_values,
                    chart_values=chart_values,
                )
                check(
                    f"install/parity::per-install-hostnames[{name}]",
                    not asymmetric,
                    detail="; ".join(asymmetric),
                )
            # Database-grant isolation (INT-FOUNDRY-040/041): a provisioning
            # Job carries the per-app credential and the PG16 SET-role grant.
            if any(
                d.get("kind") == "Job"
                and str((d.get("metadata") or {}).get("name") or "")
                == f"pg-{name}-provision"
                for d in docs
            ):
                jobs_text = self._team_text(name, "jobs.yaml") or ""
                check(
                    f"install/database::isolation-clean[{name}]",
                    database_job_is_isolation_clean(job_text=jobs_text, app=name),
                )
        return results

    def _prefetch(self, app_names: list[str]) -> None:
        """Warm the repo-host cache concurrently, before the checks read it.

        Every app-side leg reads through ``_cached_read``, so priming that cache
        IS the whole optimisation: the check loop is untouched - same order, same
        rows, same outcomes - and simply finds each read already answered. Issued
        one at a time, those reads were ~90s on a cold cache, longer than the OIDC
        proxy in front of the studio waits, so the answer was lost at the edge
        rather than merely slow.

        Two waves, because a file read needs the branch to read it off: the repo
        facts first, then the files hanging off the default branch. A path this
        misses is not wrong, only slower - the loop reads it inline as it always
        did - so this never becomes a second authority on what the checks mean.
        """
        if self._app_repo is None:
            return
        # One entry per distinct Application source: several apps can name the
        # same repo, and re-reading it would spend a round trip on a cache hit.
        sources: dict[tuple[str, str, str], dict] = {}
        for name in app_names:
            for doc in self._team_docs(name):
                if doc.get("kind") != "Application":
                    continue
                source = (doc.get("spec") or {}).get("source") or {}
                repo_url = str(source.get("repoURL") or "")
                if not repo_url:
                    continue
                key = (
                    repo_url,
                    str(source.get("targetRevision") or ""),
                    str(source.get("path") or ""),
                )
                sources.setdefault(key, source)
        if not sources:
            return

        repo_facts: list[Callable[[], object]] = []
        for (repo_url, branch, _), source in sources.items():
            repo_facts.append(lambda u=repo_url: self._repo_exists(u))
            repo_facts.append(lambda u=repo_url: self._default_branch(u))
            repo_facts.append(lambda s=source: self._deploy_values(s))
            if branch:
                repo_facts.append(lambda u=repo_url, b=branch: self._branch_paths(u, b))

        paths = _DEFAULT_BRANCH_FILES + (_ACT_BRANCH_FILES if self._act_rows else ())
        files: list[Callable[[], object]] = [
            lambda u=repo_url, p=path: self._prefetch_file(u, p)
            for repo_url in {url for url, _, _ in sources}
            for path in paths
        ]

        with ThreadPoolExecutor(max_workers=_PREFETCH_WORKERS) as pool:
            self._drain(pool, repo_facts)
            self._drain(pool, files)

    def _prefetch_file(self, repo_url: str, path: str) -> None:
        """Warm one default-branch file read; the branch itself is already cached
        by the first wave, so this costs one round trip rather than two."""
        default = self._default_branch(repo_url)
        if default is not None:
            self._file_text(repo_url, default, path)

    @staticmethod
    def _drain(pool: ThreadPoolExecutor, work: list[Callable[[], object]]) -> None:
        """Run every thunk to completion, swallowing failures: a warm-up is an
        optimisation and must never fail a run the sequential reads would pass.
        Whatever it could not warm, the check loop reads inline and reports on."""
        for future in [pool.submit(thunk) for thunk in work]:
            try:
                future.result()
            except Exception:  # noqa: BLE001 - a warm-up failure is not a verdict
                logger.debug("Conformance prefetch read failed", exc_info=True)

    def _cached_read(self, key: tuple[str, ...], read: Callable[[], object]) -> object:
        """One repo-host read, cached for _REPO_TTL_SECONDS so a gate's
        baseline and candidate runs judge the same snapshot."""
        now = time.monotonic()
        cached = self._repo_cache.get(key)
        if cached is None or now - cached[0] > _REPO_TTL_SECONDS:
            cached = (now, read())
            self._repo_cache[key] = cached
        return cached[1]

    def _deploy_values(self, source: dict) -> dict | None:
        """The app's deploy values named by its Application source, cached;
        None without a wired source or when they cannot be read."""
        if self._app_repo is None:
            return None
        app_repo = self._app_repo
        repo_url = str(source.get("repoURL") or "")
        branch = str(source.get("targetRevision") or "")
        env_path = str(source.get("path") or "").strip("/")
        path = f"{env_path}/values.yaml" if env_path and env_path != "." else "values.yaml"
        values = self._cached_read(
            ("deploy-values", repo_url, branch, path),
            lambda: app_repo.deploy_values(repo_url=repo_url, branch=branch, path=path),
        )
        return values if isinstance(values, dict) else None

    def _chart_values(self, source: dict) -> dict | None:
        """The app chart's own ``k8s/values.yaml``, off the repo's default
        branch (the chart source, not the deploy branch's rendered values);
        None without a wired source or when it cannot be read."""
        repo_url = str(source.get("repoURL") or "")
        default = self._default_branch(repo_url) if repo_url else None
        if default is None:
            return None
        text = self._file_text(repo_url, default, "k8s/values.yaml")
        if text is None:
            return None
        try:
            parsed = yaml.safe_load(text)
        except yaml.YAMLError:
            return None
        return parsed if isinstance(parsed, dict) else None

    def _released_set(self, app: str, source: dict) -> tuple[str, ...] | None:
        """The GHCR packages the app repo's CI publishes (the compose build:
        services plus the docs image), derived off the repo's default branch;
        None without a wired source or when the repo, its compose, or its
        docs/Dockerfile cannot be read (an empty docs read the branch listing
        does not confirm as absent)."""
        repo_url = str(source.get("repoURL") or "")
        default = self._default_branch(repo_url) if repo_url else None
        if default is None:
            return None
        text = self._file_text(repo_url, default, "devops/docker-compose.yml")
        if text is None:
            return None
        try:
            compose = yaml.safe_load(text)
        except yaml.YAMLError:
            return None
        if not isinstance(compose, dict):
            return None
        docs = self._file_text(repo_url, default, "docs/Dockerfile")
        if docs is None and self._unanswered(repo_url, default, "docs/Dockerfile"):
            return None
        return released_packages(app=app, compose=compose, docs_image=docs is not None)

    def _repo_exists(self, repo_url: str) -> bool | None:
        """Whether the app repo is visible at all, cached; None without a
        wired source or when the answer proves nothing."""
        if self._app_repo is None:
            return None
        app_repo = self._app_repo
        visible = self._cached_read(
            ("repo-exists", repo_url),
            lambda: app_repo.repo_exists(repo_url=repo_url),
        )
        return visible if isinstance(visible, bool) else None

    def _default_branch(self, repo_url: str) -> str | None:
        """The app repo's default branch, cached; None without a wired source
        or when the repo cannot be read."""
        if self._app_repo is None:
            return None
        app_repo = self._app_repo
        branch = self._cached_read(
            ("default-branch", repo_url),
            lambda: app_repo.default_branch(repo_url=repo_url),
        )
        return branch if isinstance(branch, str) else None

    def _file_text(self, repo_url: str, branch: str, path: str) -> str | None:
        """One file's raw text off the app repo, cached; None without a wired
        source or when it cannot be read."""
        if self._app_repo is None:
            return None
        app_repo = self._app_repo
        text = self._cached_read(
            ("file-text", repo_url, branch, path),
            lambda: app_repo.file_text(repo_url=repo_url, branch=branch, path=path),
        )
        return text if isinstance(text, str) else None

    def _unanswered(self, repo_url: str, branch: str, path: str) -> bool:
        """Whether a file read that came back empty only went unanswered.

        ``_file_text`` answers None for a file the branch lacks and equally for
        a read the host never answered (a timeout, a reset connection), so an
        empty read settles nothing on its own. The branch listing settles it: a
        listing that answers without ``path`` is a verified absence (False); a
        listing that carries ``path``, or that cannot be read, leaves the read
        unanswered (True), and the row reports skipped.
        """
        paths = self._branch_paths(repo_url, branch)
        return paths is None or path in paths

    def _branch_paths(self, repo_url: str, branch: str) -> frozenset[str] | None:
        """The file paths a branch carries, cached; None without a wired
        source or when the branch cannot be read."""
        if self._app_repo is None:
            return None
        app_repo = self._app_repo
        paths = self._cached_read(
            ("branch-paths", repo_url, branch),
            lambda: app_repo.branch_paths(repo_url=repo_url, branch=branch),
        )
        return paths if isinstance(paths, frozenset) else None

    def _yaml(self, rel_path: str) -> dict:
        path = self._root / rel_path
        if not path.is_file():
            return {}
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    def _team_folders(self) -> list[str]:
        teams = self._root / "teams"
        if not teams.is_dir():
            return []
        return sorted(p.name for p in teams.iterdir() if p.is_dir())

    def _team_text(self, app: str, filename: str) -> str | None:
        path = self._root / "teams" / app / filename
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8")

    def _team_docs(self, app: str) -> list[dict]:
        docs: list[dict] = []
        folder = self._root / "teams" / app
        if not folder.is_dir():
            return docs
        for path in sorted(folder.iterdir()):
            if not (path.is_file() and path.suffix == ".yaml"):
                continue
            text = path.read_text(encoding="utf-8")
            docs.extend(d for d in yaml.safe_load_all(text) if isinstance(d, dict))
        return docs
