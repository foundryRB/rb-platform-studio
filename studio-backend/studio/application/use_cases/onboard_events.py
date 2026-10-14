"""Use case: install-side event-bus grant, conformance-gated, PR-mode."""

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
from studio.domain.services.change_branch import events_branch
from studio.domain.services.events_grant import normalise_domains, render_events_grant
from studio.domain.services.team_documents import append_document, split_by_concern
from studio.logging import get_logger

__all__ = ["OnboardEvents"]

logger = get_logger(__name__)


class OnboardEvents:
    """Implements OnboardEventsPort: render the events grant from a template.

    Bus access is granted like a database or a realm: a declarative block
    admitted by merge into the deploy branch (the platform repo's CI performs
    it, platform ADR-036). The blocks are rendered from the studio-owned canonical
    template (``events_grant``) rather than copied off a live app, because their
    invariants are not a function of the app name and would not survive a
    rename: the app's seed secret carries no reflector annotation at all, only
    the derived public key reflects into ``messaging``, the signed JWT reflects
    back, and the publish scope is the declared domains plus the one shared
    stream's API rather than the whole JetStream surface.

    The domains are the caller's to declare and the review's to judge. The
    studio deliberately holds no domain registry: the grant is what makes an
    app a domain's owner, a duplicate prefix across an install's teams is
    caught by the platform's own conformance (INT-FOUNDRY-066), and the types
    an owner publishes are stated on its own docs page, held by its own tests
    (REF-Events section 3).
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

    def execute(
        self,
        *,
        name: str,
        domains: tuple[str, ...] | list[str],
        allow_bootstrap: bool = False,
    ) -> OnboardingResult:
        if not any(entry.name == name for entry in self._repository.manifest_entries()):
            raise EntityNotFoundError("app", name)
        if not self._repository.team_files(name):
            raise EntityNotFoundError("team folder", name)
        manifest = self._repository.team_manifest(name)
        if manifest is not None and manifest.has_events:
            raise AlreadyExistsError("events", name)

        # Raises before any branch is prepared, so a malformed domain never
        # opens an empty pull request against the install's deploy branch.
        owned = normalise_domains(domains)

        grant = render_events_grant(name, owned)
        routed = split_by_concern(grant)
        touched = tuple(
            dict.fromkeys(f"teams/{name}/{filename}" for filename, _doc in routed)
        )

        def mutate() -> None:
            for filename, doc in routed:
                existing = self._repository.team_file_text(name, filename)
                self._repository.write_team_file(name, filename, append_document(existing, doc))

        logger.info(
            "Onboarding events for %s on domains %s (rendered from canonical template)",
            name,
            ", ".join(owned),
        )
        scope = ", ".join(owned)
        result = self._gated_change.execute(
            app=name,
            branch=events_branch(name),
            touched_paths=touched,
            mutate=mutate,
            commit_message=f"feat(events): grant {name} bus access for {scope}",
            pr_title=f"feat(events): grant {name} bus access for {scope}",
            pr_body=lambda baseline, report, changed: self._pr_body(
                name=name,
                domains=owned,
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
                "capability": "events",
                "branch": result.branch,
                "pr": pr_pointer(result.pr),
            },
        )
        return result

    def _pr_body(
        self,
        *,
        name: str,
        domains: tuple[str, ...],
        baseline: ConformanceReport,
        report: ConformanceReport,
        changed: tuple[str, ...],
    ) -> str:
        subjects = ", ".join(f"`com.foundry.{domain}.>`" for domain in domains)
        summary = "\n".join(
            [
                f"Event-bus grant for `{name}`, prepared by platform-studio:",
                "- key generator and signing Job rendered from the studio's canonical "
                f"template into `teams/{name}/` (per concern file)",
                f"- signed to publish {subjects} and nothing else; reading stays open "
                "across `com.foundry.>`, because REF-Events restricts speaking, not "
                "listening",
                f"- the app mints its own nkey seed in its own namespace and publishes "
                f"only the derived public key; `nats-{name}` carries no reflector "
                "annotation, so the seed never leaves. The platform signs an assertion "
                "about a key it has never seen and holds no tenant credential",
                "- a re-run never rotates a live seed (generate-if-absent, platform ADR-034); "
                "re-signing is how a scope change reaches the app",
            ]
        )
        checklist = "\n".join(
            [
                "### Onboarding checklist",
                "",
                f"- [ ] Event-bus grant intended for `{name}`",
                f"- [ ] `{name}` is the REF-Events owner of {subjects}; no other app on "
                "this install claims the same domain (one owner per domain)",
                "- [ ] The domains are bounded areas named per REF-Events section 3, "
                "not the app's own name; the types published under them are "
                f"stated on `{name}`'s own events reference page, shipped with "
                "its publisher",
            ]
        )
        return "\n\n".join(
            section
            for section in (
                f"## Onboard {name} events",
                summary,
                changed_files_section(changed),
                conformance_section(baseline, report),
                advisory_section(name, report),
                checklist,
            )
            if section
        )
