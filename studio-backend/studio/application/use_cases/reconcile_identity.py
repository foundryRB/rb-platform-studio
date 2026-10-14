"""Use case: re-render an app's realm grant against the install's current declaration."""

from __future__ import annotations

from studio.application.ports.outbound.platform_repository import PlatformRepository
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
from studio.domain.services.change_branch import reconcile_identity_branch
from studio.domain.services.identity_grant import (
    broker_callback_url,
    realm_issuer_url,
    render_identity_blocks,
)
from studio.domain.services.identity_reconcile import (
    IdentityReconciliation,
    reconcile_identity_documents,
)
from studio.logging import get_logger

__all__ = ["ReconcileIdentity"]

logger = get_logger(__name__)


class ReconcileIdentity:
    """Implements ReconcileIdentityPort: the day-2 verb a realm never had.

    ADR-045 made brokering data: the install declares ``defaultBrokers`` on its
    deploy branch and the grant splices whatever is declared into every realm it
    renders. That reaches realms granted AFTERWARDS. A realm already on the branch
    carries what it was rendered with, and the only path that rendered one -
    ``OnboardIdentity`` - refuses an app whose realm exists, while ``ReconcileApp``
    re-renders the skeleton and deliberately leaves every grant file alone. An
    install that declared a broker after granting its realms, or named a login
    theme, therefore had no way through the studio to bring them up to date,
    and ``grant_drift`` could only report the gap.

    This is the repair, in the studio's own shape: the realm blocks are rendered
    from the CURRENT canonical template (``identity_grant.py``) and the install's
    CURRENT declaration, exactly as a fresh onboarding would render them, and
    replaced in place (``identity_reconcile.py``). What that touches and what it
    does not is the whole of the contract:

    - the realm ConfigMap and its provisioning Job are replaced, document by
      document, in the concern file that carries each; the file around them is
      byte-identical (the database grant's Jobs, the ``gen-keycloak-<app>``
      generator that mints the app's own credential, its ServiceAccount and RBAC);
    - the realm's admitted users are carried across verbatim: the users list is
      the access allowlist and a render cannot know the people in it
      (INT-GRANT-007). The realm admin is the template's and is re-rendered;
    - everything else in the realm is the template's. A hand-applied provider on
      the platform's copy is superseded by the declaration; a provider a team
      wants for itself belongs in the app's own chart (ADR-045 section 2), which
      this never reads and the Job applies no-delete around;
    - the app's credential wiring is unchanged: the ``keycloak-<app>`` Secret, the
      ``<app>`` client, the host, so the sidecar and the issuer the app already
      points at need nothing.

    Idempotent by construction: a branch that already carries what the template
    renders for this declaration is refused before any branch is prepared, so a
    sweep over every realm opens a pull request only where something changed.
    The one step outside git, registering a broker's callback with its IdP, is
    the operator's and is named in the checklist for each alias the realm did not
    previously carry; an alias already brokered keeps its registration, because
    the alias fixes the callback path.
    """

    def __init__(
        self,
        repository: PlatformRepository,
        gated_change: GatedChange,
    ) -> None:
        self._repository = repository
        self._gated_change = gated_change

    def execute(self, *, name: str, allow_bootstrap: bool = False) -> OnboardingResult:
        if not any(entry.name == name for entry in self._repository.manifest_entries()):
            raise EntityNotFoundError("app", name)
        manifest = self._repository.team_manifest(name)
        if manifest is None:
            raise EntityNotFoundError("team folder", name)
        if not manifest.has_identity:
            raise EntityNotFoundError("identity realm", name)

        host = manifest.hostname
        brokers = self._repository.default_brokers()
        login_theme = self._repository.login_theme()
        rendered = render_identity_blocks(name, host, brokers, login_theme)
        team_files = {
            filename: self._repository.team_file_text(name, filename) or ""
            for filename in self._repository.team_files(name)
        }
        reconciliation = reconcile_identity_documents(
            app=name, rendered_blocks=rendered, team_files=team_files
        )
        if reconciliation.current:
            # Refused before any branch is prepared, like a settings write that
            # changes nothing: the alternative is an empty pull request against
            # the install's deploy branch.
            raise AlreadyExistsError(
                "current identity grant",
                name,
                "the realm blocks on the branch already match what the canonical "
                "template renders for this install's declared brokers and login "
                "theme; nothing to reconcile",
            )

        declared = tuple(broker.alias for broker in brokers)
        touched = tuple(f"teams/{name}/{filename}" for filename, _text in reconciliation.files)

        def mutate() -> None:
            for filename, text in reconciliation.files:
                self._repository.write_team_file(name, filename, text)

        logger.info(
            "Reconciling identity realm for %s (brokers=%s, theme=%s)",
            name,
            list(declared) or "none",
            login_theme or "keycloak's own",
        )
        return self._gated_change.execute(
            app=name,
            branch=reconcile_identity_branch(name),
            touched_paths=touched,
            mutate=mutate,
            commit_message=f"fix(identity): reconcile {name} realm",
            pr_title=f"fix(identity): reconcile {name} realm",
            pr_body=lambda baseline, report, changed: self._pr_body(
                name=name,
                host=host,
                declared=declared,
                login_theme=login_theme,
                reconciliation=reconciliation,
                baseline=baseline,
                report=report,
                changed=changed,
            ),
            allow_bootstrap=allow_bootstrap,
        )

    def _pr_body(
        self,
        *,
        name: str,
        host: str,
        declared: tuple[str, ...],
        login_theme: str,
        reconciliation: IdentityReconciliation,
        baseline: ConformanceReport,
        report: ConformanceReport,
        changed: tuple[str, ...],
    ) -> str:
        previous = reconciliation.previous_aliases
        added = tuple(alias for alias in declared if alias not in previous)
        converged = tuple(alias for alias in declared if alias in previous)
        superseded = tuple(alias for alias in previous if alias not in declared)
        previous_theme = reconciliation.previous_login_theme

        if declared:
            brokers = "- default brokers this install declares: " + ", ".join(
                f"`{alias}`" for alias in declared
            )
        else:
            brokers = (
                "- this install declares no default broker, so the realm brokers "
                "nothing and signs in against its own users"
            )
        if login_theme and previous_theme == login_theme:
            theme = f"- login theme `{login_theme}` (unchanged)"
        elif login_theme:
            theme = f"- login theme: `{previous_theme or 'keycloak default'}` -> `{login_theme}`"
        elif previous_theme:
            theme = (
                f"- login theme: `{previous_theme}` -> keycloak default (the install names none)"
            )
        else:
            theme = "- login theme: none named by the install; the realm keeps Keycloak's own"
        if reconciliation.carried_users:
            users = "- realm users carried across untouched beside the realm admin: " + ", ".join(
                f"`{user}`" for user in reconciliation.carried_users
            )
        else:
            users = "- realm users: the realm admin only (the template's), none admitted by hand"
        summary = "\n".join(
            [
                f"Re-render of `{name}`'s Keycloak realm grant, prepared by platform-studio "
                "(platform ADR-045):",
                "- the realm ConfigMap and its provisioning Job re-rendered from the CURRENT "
                "canonical template and this install's CURRENT declaration, and replaced in "
                f"place in `teams/{name}/`; every other document in the folder is byte-identical",
                brokers,
                theme,
                users,
                f"- the app's own credential wiring untouched: the `keycloak-{name}` Secret "
                f"and the `gen-keycloak-{name}` Job that mints it, the `{name}` client, the "
                f"host `{host}`",
            ]
        )

        why: list[str] = [
            "### What changed and why",
            "",
            "A realm carries what it was rendered with until it is reconciled: the "
            "declaration on this branch changed (or the template did) after this realm "
            "was granted, and `grant_drift` read it as out of date.",
            "",
        ]
        for alias in added:
            why.append(
                f"- `{alias}`: newly declared by this install; rendered into the realm "
                "as an existing-users-only broker (INT-GRANT-008), its credentials "
                "substituted from the Secret the declaration names"
            )
        for alias in converged:
            why.append(
                f"- `{alias}`: already brokered on this realm; its rendering is now the "
                "declaration's, and the provider Keycloak holds under that alias "
                "converges to it on the next sync (a hand-applied provider of the same "
                "alias is superseded)"
            )
        for alias in superseded:
            why.append(
                f"- `{alias}`: no longer declared by this install, so the grant stops "
                "converging it. Providers apply no-delete (INT-GRANT-005), so Keycloak "
                "keeps the provider as it last was: remove it in the realm, or from the "
                "app's own chart as its realm admin, if it should go"
            )
        if not (added or converged or superseded):
            why.append(
                "- no broker changed; the re-render carries the template's current "
                "shape (its login theme, its comments, its Job settings)"
            )

        checklist = [
            "### Reconcile checklist",
            "",
            f"- [ ] Re-render intended for `{name}`",
        ]
        for alias in added:
            url = broker_callback_url(host, name, alias)
            checklist += [
                f"- [ ] **Register the `{alias}` callback** (required, or that sign-in "
                "errors with `redirect_uri_mismatch`): add this exact URL to the "
                f"`{alias}` IdP's authorized redirect URIs:",
                "",
                f"    ```\n    {url}\n    ```",
                "",
            ]
        for alias in converged:
            checklist.append(
                f"- the `{alias}` callback `{broker_callback_url(host, name, alias)}` "
                "stands: the alias was already brokered on this realm and the alias "
                "fixes the path, so its registration is unchanged"
            )
        checklist.append(
            "- Nothing app-side changes: the sidecar keeps consuming "
            f"`keycloak-{name}` and the issuer `{realm_issuer_url(host, name)}` is "
            "unchanged"
        )
        return "\n\n".join(
            section
            for section in (
                f"## Reconcile {name} identity realm",
                summary,
                "\n".join(why),
                changed_files_section(changed),
                conformance_section(baseline, report),
                advisory_section(name, report),
                "\n".join(checklist),
            )
            if section
        )
