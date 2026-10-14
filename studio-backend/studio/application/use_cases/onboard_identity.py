"""Use case: install-side Keycloak realm grant, conformance-gated, PR-mode."""

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
from studio.domain.services.change_branch import identity_branch
from studio.domain.services.identity_grant import (
    broker_callback_url,
    realm_issuer_url,
    render_identity_blocks,
)
from studio.domain.services.secret_generator import keycloak_secret, render_secret_generator
from studio.domain.services.team_documents import append_document, split_by_concern
from studio.logging import get_logger

__all__ = ["OnboardIdentity"]

logger = get_logger(__name__)


class OnboardIdentity:
    """Implements OnboardIdentityPort: render the realm blocks from the studio template.

    A realm is granted like a database: declarative blocks admitted by merge
    into the deploy branch (the platform repo's CI performs it, platform ADR-036). The
    blocks carry the realm-per-app contract
    (own realm named for the app, a realm-scoped admin, and whichever default
    brokers the install declares, platform ADR-045), rendered from the studio's
    owned template (``identity_grant.py``), never copied from a donor app,
    so no neighbour's drift can propagate. The rendered documents land in the
    folder's concern files (the realm ConfigMap in config.yaml, the ServiceAccount
    in serviceaccount.yaml, the RBAC in grant-rbac.yaml, the Jobs in jobs.yaml) --
    every one of them grant-owned, never a skeleton file reconcile re-renders
    (INT-SKELETON-001). The
    steps this act cannot take itself are surfaced in the pull-request checklist so
    none is silently missed: registering each declared broker's callback (outside git
    entirely, and absent when the install declares none), and pointing the app at the
    new issuer on its own deploy branch, which is team-owned.
    Left unset, the app inherits the chart's default issuer - whichever
    install the chart was authored against - and its sidecar authenticates against
    another install's realm (foundry-platform#47).
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
        if manifest is not None and manifest.has_identity:
            raise AlreadyExistsError("identity realm", name)

        host = manifest.hostname if manifest else ""
        # The credential generator first (it mints what the realm Job and the
        # app's oauth2-proxy consume), then the realm blocks; one gated change
        # (platform ADR-034).
        generator = render_secret_generator(name, keycloak_secret(name))
        brokers = self._repository.default_brokers()
        blocks = render_identity_blocks(name, host, brokers, self._repository.login_theme())
        routed = split_by_concern(generator) + split_by_concern(blocks)
        touched = tuple(dict.fromkeys(f"teams/{name}/{filename}" for filename, _doc in routed))
        callbacks = tuple(
            (broker.alias, broker_callback_url(host, name, broker.alias)) for broker in brokers
        )
        issuer = realm_issuer_url(host, name)

        def mutate() -> None:
            for filename, doc in routed:
                existing = self._repository.team_file_text(name, filename)
                self._repository.write_team_file(name, filename, append_document(existing, doc))

        logger.info("Onboarding identity realm for %s (studio template)", name)
        result = self._gated_change.execute(
            app=name,
            branch=identity_branch(name),
            touched_paths=touched,
            mutate=mutate,
            commit_message=f"feat(identity): onboard {name} realm",
            pr_title=f"feat(identity): onboard {name} realm",
            pr_body=lambda baseline, report, changed: self._pr_body(
                name=name,
                callbacks=callbacks,
                issuer=issuer,
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
                "capability": "identity",
                "branch": result.branch,
                "pr": pr_pointer(result.pr),
            },
        )
        return result

    def _pr_body(
        self,
        *,
        name: str,
        callbacks: tuple[tuple[str, str], ...],
        issuer: str,
        baseline: ConformanceReport,
        report: ConformanceReport,
        changed: tuple[str, ...],
    ) -> str:
        if callbacks:
            brokered = "- own realm named for the app, a realm-scoped admin, and " + (
                ", ".join(f"the `{alias}` broker" for alias, _url in callbacks)
            ) + " this install declares; the realm's providers are the team's from here on"
        else:
            brokered = (
                "- own realm named for the app and a realm-scoped admin; this install "
                "declares no default broker, so the realm signs in against its own users "
                "and the team declares any broker it wants in its own chart"
            )
        summary = "\n".join(
            [
                f"Keycloak realm grant for `{name}`, prepared by platform-studio:",
                "- realm blocks rendered from the studio's owned template into "
                f"`teams/{name}/` (per concern file)",
                f"- the `keycloak-{name}` credential (clientSecret, cookieSecret, "
                "realmAdminPassword) is minted in-cluster by a generate-if-absent Job "
                "(platform ADR-034) and auto-reflects into `identity`; no app-side secret script, "
                "no out-of-band apply, and a re-run never rotates a live value",
                brokered,
            ]
        )
        callback_items: list[str] = []
        for alias, url in callbacks:
            callback_items += [
                f"- [ ] **Register the `{alias}` callback** (required, or that sign-in "
                "errors with `redirect_uri_mismatch`): add this exact URL to the "
                f"`{alias}` IdP's authorized redirect URIs:",
                "",
                f"    ```\n    {url}\n    ```",
                "",
            ]
        checklist = "\n".join(
            [
                "### Onboarding checklist",
                "",
                f"- [ ] Realm grant intended for `{name}`",
                *callback_items,
                f"- [ ] Credential is platform-minted: `gen-keycloak-{name}` generates "
                "the Secret in the app's namespace and reflects it into `identity`; the "
                "app repo ships only the oauth2-proxy sidecar in its chart (consuming "
                f"`keycloak-{name}` by name), never the credential itself",
                "- [ ] **Point the app at this realm**: turn the sidecar on and set the "
                f"issuer in `{name}`'s own deploy branch (the entry environment's values, "
                f"under `{name}:`), because the chart ships the block dormant with an "
                "empty issuer and its default belongs to whichever install it was "
                "authored against, inherited silently otherwise:",
                "",
                f"    ```yaml\n    auth:\n      oidc:\n        enabled: true\n"
                f"        issuer: {issuer}\n    ```",
                "",
                "    Both keys or neither: a block left off consumes nothing, which the "
                "`install/credentials::demand-grant` conformance row reports against this "
                "grant, and once it is on the "
                "`install/parity::per-install-hostnames` row fails until the issuer "
                "names this install's zone.",
            ]
        )
        return "\n\n".join(
            section
            for section in (
                f"## Onboard {name} identity realm",
                summary,
                changed_files_section(changed),
                conformance_section(baseline, report),
                advisory_section(name, report),
                checklist,
            )
            if section
        )
