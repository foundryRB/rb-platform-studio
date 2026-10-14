"""Use case: install-side app offboarding, conformance-gated, PR-mode."""

from __future__ import annotations

from studio.application.ports.outbound.event_publisher import EventPublisher
from studio.application.ports.outbound.platform_repository import PlatformRepository
from studio.application.services.event_types import APP_OFFBOARDED, pr_pointer, state_fact
from studio.application.services.gated_change import GatedChange
from studio.application.services.pr_body import changed_files_section, conformance_section
from studio.domain.exceptions.entity_not_found_error import EntityNotFoundError
from studio.domain.exceptions.self_offboard_error import SelfOffboardError
from studio.domain.model.conformance_report import ConformanceReport
from studio.domain.model.onboarding_result import OnboardingResult
from studio.domain.services.change_branch import offboard_branch
from studio.logging import get_logger

__all__ = ["OffboardApp"]

logger = get_logger(__name__)


class OffboardApp:
    """Implements OffboardAppPort: remove the whole record, gate, ship the PR.

    The manifest entry and the teams/<app>/ folder leave in ONE change, so the
    manifest-to-teams bijection (INT-FOUNDRY-001) holds on both sides of the
    merge; a half-removal fails the gate and rolls back byte-identical. The
    merge prunes the app's namespace (REF-Foundry section 10), deleting every
    volume the app's own chart claims, with its data on a Delete reclaim
    policy; the pull request merges moments after it opens, so that data is
    copied out before the act, and the pull request body states the deletion.
    The app repo is the team's, and a granted database or realm keeps its data
    on the shared instance until the platform's own teardown runbook is
    executed against an explicitly authorized disposition - this use case
    enumerates those grants in the pull request instead of destroying them.
    Offboarding is what frees the name, once those grants are dropped too,
    since a grant for a reused name provisions onto whatever the shared
    instance still holds. A GitHub-side repo rename leaves every one of these
    artifacts standing and collides with the next delivery for the name.
    """

    def __init__(
        self,
        repository: PlatformRepository,
        gated_change: GatedChange,
        self_app: str,
        events: EventPublisher | None = None,
    ) -> None:
        self._repository = repository
        self._gated_change = gated_change
        self._self_app = self_app
        self._events = events

    def execute(self, *, name: str) -> OnboardingResult:
        if name == self._self_app:
            raise SelfOffboardError(name)
        if not any(entry.name == name for entry in self._repository.manifest_entries()):
            raise EntityNotFoundError("app", name)
        files = self._repository.team_files(name)
        if not files:
            raise EntityNotFoundError("team folder", name)
        manifest = self._repository.team_manifest(name)
        has_database = manifest is not None and manifest.has_database
        has_identity = manifest is not None and manifest.has_identity
        hostname = manifest.hostname if manifest is not None else ""

        touched = ("foundry.yaml",) + tuple(f"teams/{name}/{f}" for f in files)

        def mutate() -> None:
            self._repository.remove_manifest_entry(name)
            for filename in files:
                self._repository.raw_delete(f"teams/{name}/{filename}")

        logger.info(
            "Offboarding %s (%d team files; database=%s identity=%s)",
            name,
            len(files),
            has_database,
            has_identity,
        )
        result = self._gated_change.execute(
            app=name,
            branch=offboard_branch(name),
            touched_paths=touched,
            mutate=mutate,
            commit_message=f"feat(teams): offboard {name}",
            pr_title=f"feat(teams): offboard {name}",
            pr_body=lambda baseline, report, changed: self._pr_body(
                name=name,
                hostname=hostname,
                files=files,
                has_database=has_database,
                has_identity=has_identity,
                baseline=baseline,
                report=report,
                changed=changed,
            ),
        )
        # The offboarding pull request is open before the fact is stated; the
        # event carries the app and the pointer, never the removed files.
        state_fact(
            self._events,
            event_type=APP_OFFBOARDED,
            subject=name,
            data={"app": name, "branch": result.branch, "pr": pr_pointer(result.pr)},
        )
        return result

    def _pr_body(
        self,
        *,
        name: str,
        hostname: str,
        files: tuple[str, ...],
        has_database: bool,
        has_identity: bool,
        baseline: ConformanceReport,
        report: ConformanceReport,
        changed: tuple[str, ...],
    ) -> str:
        summary = "\n".join(
            [
                f"Install-side offboarding of `{name}`, prepared by platform-studio:",
                f"- the `foundry.yaml` entry and the whole `teams/{name}/` folder "
                "removed together, so the manifest-to-teams bijection stays exact "
                "(INT-FOUNDRY-001)",
                "- on sync, pruning the Application removes the workloads, and "
                "deleting the Namespace deletes every volume the app's chart claims "
                "in it, with its data on a `Delete` reclaim policy; removing the "
                f"Gateway frees `{hostname or f'{name}.<zone>'}` and its DNS record",
                "- every manifest-derived view (docs index, homepage, dashboards) "
                "drops the app on the next sync; nothing to re-run",
                "- the app's own source repo is untouched: retiring it is the owning "
                "team's call",
            ]
        )
        disposition = self._disposition_section(
            name=name, has_database=has_database, has_identity=has_identity
        )
        frees = (
            f"the name `{name}` is free for reuse once each grant above is dropped"
            if disposition
            else f"this frees the name `{name}` for reuse"
        )
        checklist_items = [
            "### Offboarding checklist",
            "",
            f"- [ ] Retirement intended (pause is the reversible alternative and "
            f"destroys nothing); {frees}",
            f"- [ ] Team folder removed in full: {', '.join(f'`{f}`' for f in files)}",
            "- [ ] Volumes the app's chart claims copied out before this PR opened "
            "(it merges on open), or recorded here as not kept",
        ]
        if disposition:
            checklist_items.append(
                "- [ ] Stateful teardown (above) decided explicitly, never defaulted"
            )
        checklist = "\n".join(checklist_items)
        return "\n\n".join(
            section
            for section in (
                f"## Offboard {name}",
                summary,
                changed_files_section(changed),
                conformance_section(baseline, report),
                disposition,
                checklist,
            )
            if section
        )

    @staticmethod
    def _disposition_section(*, name: str, has_database: bool, has_identity: bool) -> str:
        """The stateful grants this removal orphans, enumerated for a decision.

        Removing a grant's provisioning blocks stops provisioning; it does NOT
        drop the database on the shared PostgreSQL or the realm on the shared
        Keycloak, and their data persists until the platform's own teardown
        runbook runs. That drop is irreversible and therefore never part of
        this pull request: it is executed out of band, against the recorded
        disposition, or deliberately not at all (retain for backup/migration).
        """
        if not has_database and not has_identity:
            return ""
        lines = [
            "### Data disposition (decide explicitly)",
            "",
            "This app carried stateful grants, held on the shared instances "
            "outside its namespace. The merge removes their provisioning "
            "wiring and the credentials minted in the namespace; their data "
            "persists on the shared instances until the platform's teardown "
            "runbook is executed against a recorded decision:",
            "",
        ]
        if has_database:
            lines.append(
                f"- database `{name}` on the shared PostgreSQL (owner role "
                f"`{name}`, credential `pg-app-{name}`, whose deletion ends the "
                "least-privilege dump, so that dump was due before this PR "
                "opened): drop it, or retain it for a backup or migration"
            )
        if has_identity:
            lines.append(
                f"- realm `{name}` on the shared Keycloak (client, realm-admin, "
                f"credential `keycloak-{name}`): delete it, or retain; the shared "
                "IdP's callback registration for it should be removed either way"
            )
        return "\n".join(lines)
