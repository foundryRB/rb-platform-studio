"""The one shape every install mutation takes: branch, mutate, gate, PR or rollback."""

from __future__ import annotations

from collections.abc import Callable

from studio.application.ports.outbound.conformance_runner import ConformanceRunner
from studio.application.ports.outbound.event_publisher import EventPublisher
from studio.application.ports.outbound.git_pr import GitPr
from studio.application.ports.outbound.platform_repository import PlatformRepository
from studio.application.services.event_types import CHANGE_OPENED, pr_pointer, state_fact
from studio.application.services.pr_body import bootstrap_waiver_section
from studio.domain.exceptions.unverified_legs_error import APP_SIDE_LEGS, UnverifiedLegsError
from studio.domain.exceptions.validation_failed_error import ValidationFailedError
from studio.domain.model.conformance_report import ConformanceReport
from studio.domain.model.onboarding_result import OnboardingResult
from studio.domain.model.test_outcome import TestOutcome
from studio.domain.services.credential_demand import DEMAND_GRANT_ROW
from studio.logging import get_logger

__all__ = ["ADVISORY_ROWS", "GatedChange"]

logger = get_logger(__name__)

# Conformance rows the gate reports but never refuses on. The credential
# demand-grant cross-check (INT-GRANT-004) names a state only a later
# onboarding can resolve: the grant it asks for is rendered into
# teams/<app>/, which onboard_app must create first, and onboard_identity /
# onboard_database refuse an app the manifest does not yet carry. Admitting on
# it would deadlock every app whose chart already reads a platform-minted
# Secret - the app onboarding refused for a missing grant, the grant's
# onboarding refused for a missing app. It surfaces in run_conformance and in
# the app's status chain, where acting on it has no ordering trap, and in the
# pull-request body of every onboarding that leaves it failing.
ADVISORY_ROWS: tuple[str, ...] = (DEMAND_GRANT_ROW,)


class GatedChange:
    """Runs one conformance-gated mutation of the install checkout.

    The gate is a baseline diff: the change may not introduce any conformance
    failure that the deploy branch does not already have, save the advisory
    rows (ADVISORY_ROWS), which report without refusing because the state they
    name is only resolvable by a later onboarding. Admission is also
    strict on the app's own delivery legs: a candidate row for the app that
    reports skipped among the app-side legs (APP_SIDE_LEGS: the CI caller,
    the deploy branch, the Image Updater values binding, the released-set
    binding) refuses the change,
    because a skipped leg means the app's team-owned artifacts could not be
    read and the change would ship entirely unverified on that side. The
    explicit allow_bootstrap waiver admits those skips (the deliberate
    walking-skeleton bootstrap, REF-Foundry) and the pull-request body records
    the waiver. On a passed gate the change is committed on its onboarding
    branch and offered as a pull request against the deploy branch (or, in
    the local composition, left in the working tree). On a failed gate every
    touched file is restored byte-identical and the branch is discarded, and
    so it is when the gate passes but publishing then fails: a change that
    could not be offered leaves nothing behind either.
    Every file a change may touch is authored (the manifest entry, the
    teams/<app>/ files); manifest-derived views are rendered by the platform
    chart and never exist as files here.
    """

    def __init__(
        self,
        repository: PlatformRepository,
        conformance: ConformanceRunner,
        git: GitPr,
        events: EventPublisher | None = None,
    ) -> None:
        self._repository = repository
        self._conformance = conformance
        self._git = git
        self._events = events

    def execute(
        self,
        *,
        app: str,
        branch: str,
        touched_paths: tuple[str, ...],
        mutate: Callable[[], None],
        commit_message: str,
        pr_title: str,
        pr_body: Callable[[ConformanceReport, ConformanceReport, tuple[str, ...]], str],
        allow_bootstrap: bool = False,
    ) -> OnboardingResult:
        baseline = self._conformance.run()
        all_paths = tuple(dict.fromkeys(touched_paths))
        snapshot = {path: self._repository.raw_read(path) for path in all_paths}
        self._git.prepare_branch(branch)
        try:
            mutate()
            report = self._conformance.run()
        except Exception:
            self._restore(snapshot)
            self._git.abort(branch)
            raise
        introduced = report.failing_ids() - baseline.failing_ids()
        new_failures = tuple(
            sorted(
                node_id
                for node_id in introduced
                if not node_id.startswith(ADVISORY_ROWS)
            )
        )
        suite_broken = report.exit_code not in (0, 1)
        if new_failures or suite_broken:
            if suite_broken and not new_failures:
                new_failures = (f"conformance suite exited {report.exit_code}",)
            logger.warning("Gate failed for %s; rolling back: %s", app, ", ".join(new_failures))
            self._restore(snapshot)
            self._git.abort(branch)
            raise ValidationFailedError(report, new_failures)
        skipped_legs = tuple(
            result.node_id
            for result in report.for_app(app)
            if result.outcome is TestOutcome.SKIPPED
            and result.node_id.startswith(tuple(APP_SIDE_LEGS))
        )
        if skipped_legs and not allow_bootstrap:
            logger.warning(
                "Admission refused for %s; app-side legs unverified, rolling back: %s",
                app,
                ", ".join(skipped_legs),
            )
            self._restore(snapshot)
            self._git.abort(branch)
            raise UnverifiedLegsError(report, skipped_legs)
        changed = tuple(
            path for path in all_paths if self._repository.raw_read(path) != snapshot[path]
        )
        try:
            # The body is pure composition and should never raise, which is
            # exactly why it must sit inside the rollback: a composition bug
            # is the one failure a later act cannot recover from, since it
            # leaves the tree mutated and the branch prepared (#24).
            body = pr_body(baseline, report, changed)
            if skipped_legs:
                body = f"{body}\n\n{bootstrap_waiver_section(skipped_legs)}"
            pr = self._git.finalize(
                branch=branch,
                commit_message=commit_message,
                pr_title=pr_title,
                pr_body=body,
            )
        except Exception:
            # A passed gate does not make publishing succeed: the push and the
            # pull request are two writes against two systems. The rollback is
            # the same one a failed gate takes, so a change that could not be
            # published is indistinguishable from one never attempted.
            logger.warning("Publishing failed for %s; rolling back %s", app, branch)
            self._restore(snapshot)
            self._git.abort(branch)
            raise
        logger.info(
            "Gate passed for %s: %d file(s) changed, %s",
            app,
            len(changed),
            pr.url if pr else "left in working tree (local run)",
        )
        # The pull request exists before the fact is stated, and only when one
        # does: the local composition opens none, so it narrates nothing here.
        # One fact for every gated act, so a consumer waiting on "a change is
        # awaiting admission" subscribes to one type rather than to each act's.
        if pr is not None and self._events is not None:
            state_fact(
                self._events,
                event_type=CHANGE_OPENED,
                subject=app,
                data={
                    "subject": app,
                    "branch": branch,
                    "pr": pr_pointer(pr),
                    "title": pr_title,
                    "changed_files": len(changed),
                },
            )
        return OnboardingResult(
            app=app,
            changed_files=changed,
            baseline=baseline,
            report=report,
            branch=branch if pr else None,
            pr=pr,
        )

    def _restore(self, snapshot: dict[str, str | None]) -> None:
        for path, content in snapshot.items():
            if content is None:
                self._repository.raw_delete(path)
            else:
                self._repository.raw_write(path, content)
