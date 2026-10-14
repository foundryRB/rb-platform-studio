"""Use case: install-side database grant, conformance-gated, PR-mode."""

from __future__ import annotations

from studio.application.ports.outbound.event_publisher import EventPublisher
from studio.application.ports.outbound.platform_repository import PlatformRepository
from studio.application.services.event_types import GRANT_ISSUED, pr_pointer, state_fact
from studio.application.services.gated_change import GatedChange
from studio.application.services.pr_body import (
    advisory_section,
    changed_files_section,
    conformance_section,
)
from studio.domain.exceptions.already_exists_error import AlreadyExistsError
from studio.domain.exceptions.entity_not_found_error import EntityNotFoundError
from studio.domain.model.conformance_report import ConformanceReport
from studio.domain.model.onboarding_result import OnboardingResult
from studio.domain.services.change_branch import database_branch
from studio.domain.services.database_grant import render_database_job
from studio.domain.services.secret_generator import pg_app_secret, render_secret_generator
from studio.domain.services.team_documents import append_document, split_by_concern
from studio.logging import get_logger

__all__ = ["OnboardDatabase"]

logger = get_logger(__name__)


class OnboardDatabase:
    """Implements OnboardDatabasePort: render the provisioning Job from a template.

    A database is granted like a hostname: a declarative block admitted by
    merge into the deploy branch (the platform repo's CI performs it,
    platform ADR-036). Like the team-folder skeleton
    (rendered from studio.domain.services.team_skeleton), the provisioning Job is
    rendered from the studio-owned canonical template (database_grant),
    because its isolation invariants (a per-app credential name, the PG16
    SET-role self-grant, ownership, connect lockdown) are not a function of the
    app name and so cannot survive being copied off a live app and renamed. The
    rendered documents land in the folder's concern files (the ServiceAccount in
    serviceaccount.yaml, the RBAC in grant-rbac.yaml, the Jobs in jobs.yaml) --
    every one of them grant-owned, never a skeleton file reconcile re-renders
    (INT-SKELETON-001) -- and the
    gate validates the whole candidate state on the same PR-or-working-tree path
    as app onboarding.
    """

    def __init__(
        self,
        repository: PlatformRepository,
        gated_change: GatedChange,
        events: EventPublisher | None = None,
    ) -> None:
        self._repository = repository
        self._gated_change = gated_change
        self._events = events

    def execute(self, *, name: str, allow_bootstrap: bool = False) -> OnboardingResult:
        if not any(entry.name == name for entry in self._repository.manifest_entries()):
            raise EntityNotFoundError("app", name)
        if not self._repository.team_files(name):
            raise EntityNotFoundError("team folder", name)
        manifest = self._repository.team_manifest(name)
        if manifest is not None and manifest.has_database:
            raise AlreadyExistsError("database", name)

        # The credential generator first (it mints what the Job consumes),
        # then the provisioning Job; both in one gated change (platform ADR-034).
        generator = render_secret_generator(name, pg_app_secret(name))
        job = render_database_job(name)
        routed = split_by_concern(generator) + split_by_concern(job)
        touched = tuple(
            dict.fromkeys(f"teams/{name}/{filename}" for filename, _doc in routed)
        )

        def mutate() -> None:
            for filename, doc in routed:
                existing = self._repository.team_file_text(name, filename)
                self._repository.write_team_file(name, filename, append_document(existing, doc))

        logger.info("Onboarding database for %s (rendered from canonical template)", name)
        result = self._gated_change.execute(
            app=name,
            branch=database_branch(name),
            touched_paths=touched,
            mutate=mutate,
            commit_message=f"feat(databases): onboard {name} database",
            pr_title=f"feat(databases): onboard {name} database",
            pr_body=lambda baseline, report, changed: self._pr_body(
                name=name,
                baseline=baseline,
                report=report,
                changed=changed,
            ),
            allow_bootstrap=allow_bootstrap,
        )
        # The grant's pull request is open before the fact is stated. The event
        # names the capability and points at the pull request; the rendered
        # blocks stay on the branch (REF-Events section 5).
        state_fact(
            self._events,
            event_type=GRANT_ISSUED,
            subject=name,
            data={
                "app": name,
                "capability": "database",
                "branch": result.branch,
                "pr": pr_pointer(result.pr),
            },
        )
        return result

    def _pr_body(
        self,
        *,
        name: str,
        baseline: ConformanceReport,
        report: ConformanceReport,
        changed: tuple[str, ...],
    ) -> str:
        summary = "\n".join(
            [
                f"Database grant for `{name}`, prepared by platform-studio:",
                "- provisioning Job rendered from the studio's canonical template "
                f"into `teams/{name}/` (per concern file)",
                f"- the `pg-app-{name}` credential is minted in-cluster by a "
                "generate-if-absent Job (platform ADR-034) and auto-reflects into `databases`; "
                "no app-side secret script, no out-of-band apply, and a re-run never "
                "rotates a live value",
                "- own database and least-privilege owner role, `CONNECT` revoked from "
                "`PUBLIC`; the platform never holds or reads the credential value",
            ]
        )
        checklist = "\n".join(
            [
                "### Onboarding checklist",
                "",
                f"- [ ] Database grant intended for `{name}`",
                f"- [ ] Credential is platform-minted: `gen-pg-app-{name}` generates "
                "the Secret in the app's namespace and reflects it into `databases`; "
                "the app repo ships no database credential",
            ]
        )
        return "\n\n".join(
            section
            for section in (
                f"## Onboard {name} database",
                summary,
                changed_files_section(changed),
                conformance_section(baseline, report),
                advisory_section(name, report),
                checklist,
            )
            if section
        )
