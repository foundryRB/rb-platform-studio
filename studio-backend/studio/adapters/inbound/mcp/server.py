"""MCP inbound adapter: tools mirroring the inbound ports (streamable HTTP).

A third door into the same use cases as the SPA and REST: every onboarding
goes through the identical gate-validate-rollback path and ships as a pull
request the platform repo's CI merges on open (ADR-036). The tool list derives from the
capability wiring, so the PR surface exists only when the composition manages
the clone.

Serialization reuses the HTTP DTO mappers: the OpenAPI contract is the studio's
single serialization surface, and the MCP tools mirror it mechanically rather
than maintaining a parallel shape.
"""

from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings

from studio.adapters.inbound.http.mappers.app_mapper import map_app
from studio.adapters.inbound.http.mappers.app_status_mapper import map_app_status
from studio.adapters.inbound.http.mappers.claim_mapper import map_claim
from studio.adapters.inbound.http.mappers.conformance_mapper import map_conformance_report
from studio.adapters.inbound.http.mappers.onboarding_mapper import map_onboarding_result
from studio.adapters.inbound.http.mappers.platform_setting_mapper import map_platform_setting
from studio.adapters.inbound.http.mappers.pr_mapper import map_cancelled_change, map_pr_info
from studio.adapters.inbound.work import run_serialized
from studio.container import Container
from studio.domain.exceptions.already_exists_error import AlreadyExistsError
from studio.domain.exceptions.app_error import AppError
from studio.domain.exceptions.invalid_app_name_error import InvalidAppNameError
from studio.domain.exceptions.self_offboard_error import SelfOffboardError
from studio.domain.exceptions.unverified_legs_error import UnverifiedLegsError
from studio.domain.exceptions.validation_failed_error import ValidationFailedError

__all__ = ["build_mcp_server"]

_INSTRUCTIONS = (
    "Onboarding and management surface for one Foundry install: the install's "
    "deploy branch of the platform repo is the datastore ArgoCD reconciles "
    "(ADR-032). Reads return the install manifest (foundry.yaml), team-folder "
    "facts, and conformance reports; onboardings add the app's manifest entry "
    "and render its teams/<app>/ folder, are gated by the install conformance "
    "checks, roll back byte-identical when the gates fail, and ship as pull "
    "requests based against the deploy branch, admitted by the platform "
    "repo's own CI moments after they open (ADR-036) - the studio never "
    "commits onboarding changes to the deploy branch directly, and the PR is "
    "never merged by hand. Platform settings ride the same gated path: "
    "list_platform_settings reads the curated retention and runner knobs off "
    "the branch and "
    "update_platform_setting tunes one "
    "as a pull request, carrying the value only. The installed chart must "
    "bind the field to .Values for the value to take effect. "
    "Lifecycle toggles are the one exception: they scale "
    "an app to zero (pause_app / resume_app) or hold it on its current version "
    "(freeze_promotion / resume_promotion) with a direct commit, since they "
    "admit no app and grant no hostname. Everything team-owned "
    "(your app repo's deploy branch, secrets) is yours to execute: the "
    "onboard-app prompt is the runbook."
)

_ALLOWED_HOSTS_ENV = "STUDIO_MCP_ALLOWED_HOSTS"


def _transport_security() -> TransportSecuritySettings | None:
    """DNS-rebinding protection for the transport.

    The SDK default admits localhost only, which is right for the local run.
    A deployment serves on a public hostname, so the chart supplies it via
    $STUDIO_MCP_ALLOWED_HOSTS (comma-separated Host header values).
    """
    raw = os.environ.get(_ALLOWED_HOSTS_ENV)
    if not raw:
        return None
    hosts = [h.strip() for h in raw.split(",") if h.strip()]
    return TransportSecuritySettings(allowed_hosts=hosts)


def build_mcp_server(container: Container) -> FastMCP:
    """Build the MCP server over the container's wired use cases."""
    server = FastMCP(
        "platform-studio",
        instructions=_INSTRUCTIONS,
        streamable_http_path="/",
        stateless_http=True,
        transport_security=_transport_security(),
    )

    @server.tool()
    async def list_apps() -> list[dict[str, object]]:
        """Return every app the install manifest declares, with its team-folder facts."""
        apps = await run_serialized(lambda: container.list_apps().execute())
        return [map_app(app).model_dump() for app in apps]

    @server.tool()
    async def get_app(name: str) -> dict[str, object]:
        """Return one declared app: manifest entry, hostname, repo, database, MCP."""
        app = await run_serialized(lambda: container.get_app().execute(name=name))
        return map_app(app).model_dump()

    @server.tool()
    async def app_status(name: str) -> dict[str, object]:
        """Report one app's delivery evidence chain as typed links.

        The evidence-chain read an onboarding or build run polls instead of
        improvising its own checks: onboarded (manifest entry + teams folder,
        with the hostname), onboarding_pr (an open onboard/<name> PR),
        app_repo (the app-side conformance legs: ci-caller, deploy-branch,
        image-updater bindings), ci (the latest completed workflow run on the
        app repo's default branch; a success conclusion is the chain's
        CI-green plus artifacts-published proxy), promotion (the deploy
        branch's pinned chart version, each bound image tag's current value,
        and the last write-back commit), grant_drift (whether each grant on the
        branch still matches the template that rendered it, advisory),
        credentials (every platform-minted
        credential the app's chart names - keycloak-<app>, pg-app-<app>, nats-<app> -
        having the grant in teams/<app>/ that mints it), probe (a
        cache-busted HTTPS GET of the app hostname: 200 serves, 302/401 with
        an identity grant serves behind its auth proxy, 401 without one serves
        behind the app's own auth when its /api/health answers 200, no
        response fails;
        it then reads the app's health route, which the OIDC gate skips, and
        names the running build beside the promoted tag - silent for an app
        serving no build stamp, and reporting rather than failing a mismatch,
        which is the normal state for the length of a rollout),
        smoke (the app's in-cluster deployed-smoke verdict, read off the
        platform's smoke reporter at https://docs.<zone>/smoke/<app>.json,
        ADR-047: ok on a passed result naming the tested tag beside the
        promoted one, failed on a failed or unreadable result, skipped for an
        app that has not adopted the contract or a reporter that does not
        answer; advisory, outside the stage derivation),
        sync (the primary Application sync/revision/operation read compared
        with the requested deploy head), chart (pinned and newest published OCI
        chart rendered with identical values and context), and identity_caveat.
        Links read ok, failed, pending, or skipped with observed facts.
        Serving requires promotion, sync, and probe all ok. The probe preserves
        the HTTP observation and reports pod waiting reasons, exits, and
        restart counts; unavailable workload proof keeps it skipped. Chart
        differences are advisory and keep the pin bump as the operator's act.
        Apps with an identity grant carry identity_caveat skipped, since an
        edge response cannot prove the OIDC login round-trip.
        """
        status = await run_serialized(lambda: container.app_status().execute(name=name))
        return map_app_status(status).model_dump()

    @server.tool()
    async def pause_app(name: str) -> dict[str, object]:
        """Pause an app: scale its workload to zero to free node capacity.

        Adds the scale-to-zero override to the app's ArgoCD Application and
        direct-commits it to the install's deploy branch, the one lifecycle
        exception to the PR-only rule (an operational toggle admits no app and
        grants no hostname). Docs stay served, data persists: off is not
        offboard. Refused (409), the deploy branch untouched, when the branch
        moved under the edit in a conflicting way or the file would not parse
        as YAML.
        Returns the app with its new running/paused status.
        """
        app = await run_serialized(lambda: container.pause_app().execute(name=name))
        return map_app(app).model_dump()

    @server.tool()
    async def resume_app(name: str) -> dict[str, object]:
        """Resume a paused app: remove the override and direct-commit to the
        deploy branch. Refused (409), the deploy branch untouched, when the
        branch moved under the edit in a conflicting way or the file would not
        parse as YAML."""
        app = await run_serialized(lambda: container.resume_app().execute(name=name))
        return map_app(app).model_dump()

    @server.tool()
    async def freeze_promotion(name: str) -> dict[str, object]:
        """Freeze an app's image promotion: hold it on the version it runs.

        ArgoCD Image Updater normally writes each new released tag into the
        app's deploy branch on its own, so a push to main reaches prod with no
        hand. Freezing gives every declared alias the ignore-tags filter, so
        the app keeps its current version and a new release lands only when
        someone sets the tag by hand on the deploy branch. The bindings
        themselves stay intact, so the promotion conformance rows keep running
        and the status read keeps reporting the pinned tag.

        Off is not offboard, and frozen is not paused: the app runs and serves
        as before; it just stops taking new versions. Refused (409) for an app
        whose Application declares no Image Updater bindings (nothing promotes
        it already), or one whose alias carries an operator's own ignore-tags.
        Also refused (409), the deploy branch untouched, when the branch
        moved under the edit in a conflicting way or the file would not parse
        as YAML.
        Returns the app with its new auto/manual promotion mode.
        """
        app = await run_serialized(lambda: container.freeze_promotion().execute(name=name))
        return map_app(app).model_dump()

    @server.tool()
    async def resume_promotion(name: str) -> dict[str, object]:
        """Resume a frozen app's promotion: remove the freeze tag filters and
        direct-commit to the deploy branch. Image Updater then catches the app
        up to the newest tag CI published while it was held. Refused (409),
        the deploy branch untouched, when the branch moved under the edit in a
        conflicting way or the file would not parse as YAML."""
        app = await run_serialized(lambda: container.resume_promotion().execute(name=name))
        return map_app(app).model_dump()

    @server.tool()
    async def list_claims() -> list[dict[str, object]]:
        """Return every conformance claim the platform's intent.yaml declares."""
        claims = await run_serialized(lambda: container.list_claims().execute())
        return [map_claim(c).model_dump() for c in claims]

    @server.tool()
    async def list_platform_settings() -> list[dict[str, object]]:
        """Return the curated platform knobs as the install's deploy branch has them.

        Platform-level settings (retention horizons and the ARC runner ceiling)
        the studio surfaces: each names where in the install's values its value
        lives, what the install pins there (`value`, null when it pins
        nothing), the chart's fallback (`default`), and what the component
        actually runs with (`effective`). Tune one with update_platform_setting.
        """
        settings = await run_serialized(lambda: container.list_platform_settings().execute())
        return [map_platform_setting(s).model_dump() for s in settings]

    @server.tool()
    async def update_platform_setting(key: str, value: str) -> dict[str, object]:
        """Tune one curated platform knob as a pull request.

        Writes the value into the install's values.yaml on a branch off its
        deploy branch, gated and PR-shipped exactly like an onboarding: the
        merge is the admission act, performed by the platform repo's CI
        (ADR-036), never by hand. `key` is a key from list_platform_settings;
        `value` must fit the knob's unit (a duration such as '720h' for
        retention, or a non-negative integer for the ARC runner ceiling).

        The change carries the value only. The installed chart must read the
        field from `.Values` for ArgoCD to apply it on the next sync. A knob already set to
        that value is refused rather than opening an empty pull request.
        """
        try:
            result = await run_serialized(
                lambda: container.update_platform_setting().execute(key=key, value=value)
            )
        except ValidationFailedError as exc:
            raise ToolError(_rejection(exc)) from exc
        return map_onboarding_result(result).model_dump()

    @server.tool()
    async def run_conformance() -> dict[str, object]:
        """Run the platform's conformance suite and return per-test outcomes.

        Judges the checkout as it stands: per-app rows exist only for apps
        the manifest and teams/ already carry, so a not-yet-onboarded app
        contributes no rows here. Its app-side legs (ci-caller,
        deploy-branch, image bindings) are first evaluated on the candidate
        state inside onboard_app's own gate, where readable artifacts pass
        with no waiver. The credentials::demand-grant row is advisory to that
        gate - it reports without refusing, because the grant it asks for can
        only be rendered into a teams folder an onboarding has already
        created - so this run is where a failing one is meant to be seen.
        """
        report = await run_serialized(lambda: container.run_conformance().execute())
        return map_conformance_report(report).model_dump()

    @server.tool()
    async def conformance_report(app: str) -> dict[str, object]:
        """Run the conformance suite and return only the rows for one app.

        Rows exist only for apps the manifest and teams/ already carry: a
        not-yet-onboarded app answers an empty row set here, and its
        app-side legs are first evaluated on the candidate state inside
        onboard_app's gate, where readable artifacts pass with no waiver.
        An empty or skipped pre-onboarding report is the baseline's
        construction, not a gap in the app's artifacts and no reason to
        pass allow_bootstrap.
        """
        report = await run_serialized(lambda: container.run_conformance().execute())
        full = map_conformance_report(report).model_dump()
        full["results"] = [
            {
                "node_id": result.node_id,
                "outcome": result.outcome.value,
                "detail": result.detail,
            }
            for result in report.for_app(app)
        ]
        return full

    @server.tool()
    async def onboard_app(
        name: str,
        display_name: str,
        description: str,
        icon: str,
        expose_mcp: bool = False,
        role: str = "output",
        image_components: list[str] | None = None,
        repo: str = "",
        allow_bootstrap: bool = False,
    ) -> dict[str, object]:
        """Prepare the install-side onboarding of an app as a pull request.

        Manifest entry in foundry.yaml (under `role`: 'parts' for apps the
        Foundry depends on, 'output' - the default - for apps it built and
        runs; `expose_mcp` sets the entry's mcp flag, the endpoint URL derives
        from the install zone) plus the teams/<name>/ folder rendered from the
        studio's canonical templates - gated by the install conformance
        checks (rolled back on failure) and offered as a PR against the deploy
        branch, merged automatically by the platform repo's CI (ADR-036).
        `image_components` names the app's released images when there is more
        than one (e.g. ['server', 'client', 'docs']): the Application then
        watches one GHCR package per component (<name>-<component>) and
        writes <name>.images.<component>.tag on the deploy branch; empty
        means the single-image shape (package <name>, <name>.image.tag).
        `name` is the FLEET name: the namespace, the hostname label, the chart,
        and the GHCR packages. `repo` is the app's repository under the org,
        the one thing the Application's repoURL points at, and it defaults to
        `name`. Pass `repo` whenever the repository is named differently from
        the app it ships (a short app name, a repository renamed since); the
        two are separate facts and neither has to bend to the other.
        Admission is strict on the app-side conformance legs, judged on the
        candidate state this call builds (a dry run before onboarding has no
        rows for the app and proves nothing about these legs): a candidate
        row for this app that reports skipped (its repo, deploy branch, or
        image bindings unreadable) refuses the onboarding; `allow_bootstrap`
        waives that for the deliberate walking-skeleton bootstrap and the
        waiver is recorded in the PR body. Dashboards, homepage bookmarks, and the
        docs index render from the manifest inside the platform chart; no
        derived file is written. Your app repo's own obligations (deploy
        branch, secrets) are NOT done here: run the onboard-app prompt.
        """
        try:
            result = await run_serialized(
                lambda: container.onboard_app().execute(
                    name=name,
                    display_name=display_name,
                    description=description,
                    icon=icon,
                    expose_mcp=expose_mcp,
                    role=role,
                    image_components=tuple(image_components or ()),
                    repo=repo,
                    allow_bootstrap=allow_bootstrap,
                )
            )
        except ValidationFailedError as exc:
            raise ToolError(_rejection(exc)) from exc
        except UnverifiedLegsError as exc:
            raise ToolError(_bootstrap_refusal(exc)) from exc
        return map_onboarding_result(result).model_dump()

    @server.tool()
    async def create_app_repo(
        name: str, display_name: str, description: str, repo: str = ""
    ) -> dict[str, object]:
        """Create a new org app repository pre-templated with the app contract.

        `name` is the app's FLEET name: the chart, the GHCR package prefix, and
        later its namespace and hostname. `repo` is the repository to create it
        in, and is a separate fact defaulting to the name - pass it whenever the
        organisation names its repositories differently from the apps they hold
        (a shared org that prefixes each fleet, say), so the app keeps a clean
        name while its repository follows the org's own convention.

        The repo is born a walking skeleton carrying the whole REF-Foundry
        contract - thin ci caller, devops/ compose (releasing <name>-app),
        k8s/ chart (pull secret, paused wiring, own-Gateway route), docs/
        Starlight site honoring DOCS_BASE (releasing <name>-docs), intent
        stubs, the commit-msg hook - so its own CI is green from the first
        push and the first conventional push releases 1.0.0. The install's
        deploy-<install> branch is stood up in the same act, pinned at that
        1.0.0. Creating the repo declares NOTHING install-side: no manifest
        entry, no hostname; run onboard_app after the first push, declaring
        image_components exactly as this returns them (['app', 'docs']).
        Refused when the repository already exists; needs the fleet write
        credential wired.
        """
        try:
            result = await run_serialized(
                lambda: container.create_app_repo().execute(
                    name=name, display_name=display_name, description=description,
                    repo=repo,
                )
            )
        except AppError as exc:
            # Named, not just described: the caller branches on which refusal
            # this is (adopt an existing repo, degrade with no credential, or
            # refuse outright on a scaffold that failed), and MCP would
            # otherwise hand it only the message. See _typed_refusal.
            raise ToolError(_typed_refusal(exc)) from exc
        return {
            "name": result.name,
            "repo_url": result.repo_url,
            "branch": result.branch,
            "deploy_branch": result.deploy_branch,
            "files": list(result.files),
            "image_components": list(result.image_components),
        }

    @server.tool()
    async def offboard_app(name: str) -> dict[str, object]:
        """Prepare the install-side offboarding of an app as a pull request.

        The inverse of onboard_app and what actually frees a name for reuse,
        once any granted database and realm under the name are dropped too (a
        grant for a reused name provisions onto whatever the shared instance
        still holds, handing the new app the old app's data). It removes the
        app's foundry.yaml entry and its whole teams/<name>/ folder in one
        gated change (the manifest-to-teams bijection holds on both sides of
        the merge), shipped as a PR against the deploy branch and admitted by
        the platform repo's CI moments after it opens (ADR-036). On sync,
        pruning the Application removes the workloads, and removing the
        Namespace deletes every PersistentVolumeClaim in it: each volume the
        app's own chart claims (absent from teams/<name>/) goes, and its data
        is ERASED on a Delete reclaim policy (local-path's). BEFORE calling
        this tool, take any least-privilege database dump, then pause the app
        and copy those volumes out (the platform guide's tear-down-a-grant,
        "Decide the backup before the merge"). Removing the Gateway frees the
        hostname and its DNS record; every manifest-derived view drops the app
        with no further step. A granted database or realm keeps its data on
        the shared instance - the PR enumerates each such grant for an
        explicit disposition decision, and the irreversible drop is the
        platform's own teardown runbook, never this tool. The app's source
        repo is untouched. Pause is the reversible alternative when the intent
        is capacity, not retirement. Refused for the studio itself.
        """
        try:
            result = await run_serialized(
                lambda: container.offboard_app().execute(name=name)
            )
        except ValidationFailedError as exc:
            raise ToolError(_rejection(exc)) from exc
        except SelfOffboardError as exc:
            raise ToolError(str(exc)) from exc
        return map_onboarding_result(result).model_dump()

    @server.tool()
    async def reconcile_app(
        name: str,
        image_components: list[str] | None = None,
        description: str = "",
        repo: str = "",
        allow_bootstrap: bool = False,
    ) -> dict[str, object]:
        """Re-render an onboarded app's teams/<name>/ folder as a pull request.

        The day-2 repair verb: onboarding freezes a declaration (the Image
        Updater aliases among it) into the rendered folder, and when the app
        grows - it releases more images, or the canonical templates evolved -
        the folder drifts from that moving truth. Reconcile re-renders the
        five skeleton files from the CURRENT templates and the FRESH
        `image_components` declaration (e.g. ['server', 'client', 'docs'];
        empty means the single-image shape; a frozen or paused app stays so,
        its new aliases frozen too), refreshes the manifest entry in
        place (description included, so the manifest stays the single source
        of the tile facts), and never touches grant files (jobs,
        serviceaccounts, realm config). The act gate is strict: bindings vs
        the deploy values, aliases vs the released set, and the docs image
        are all judged here, the one moment they are resolvable, so TWO things
        must already be true before calling this. The app's deploy branch
        carries the new values paths, or the bindings leg fails. And the
        app's DEFAULT BRANCH already publishes every component being
        declared, or the released-set leg fails: the released set is read
        off the default branch's compose, so a component declared before
        its compose service is merged is an alias watching a package the
        repo does not release, and the act is refused and rolled back.
        Merge the app-side compose change first, then reconcile. Ships as a
        PR against the deploy branch, admitted by the platform repo's CI
        (ADR-036).
        """
        try:
            result = await run_serialized(
                lambda: container.reconcile_app().execute(
                    name=name,
                    image_components=tuple(image_components or ()),
                    description=description,
                    repo=repo,
                    allow_bootstrap=allow_bootstrap,
                )
            )
        except ValidationFailedError as exc:
            raise ToolError(_rejection(exc)) from exc
        except UnverifiedLegsError as exc:
            raise ToolError(_bootstrap_refusal(exc)) from exc
        return map_onboarding_result(result).model_dump()

    @server.tool()
    async def onboard_database(name: str, allow_bootstrap: bool = False) -> dict[str, object]:
        """Prepare an app's database grant as a pull request.

        Renders from the studio's canonical template into the app's team
        folder (per concern file): the generate-if-absent credential Job
        (mints pg-app-<app> in-cluster, ADR-034) plus the provisioning Job
        (own database, least-privilege owner role, connect lockdown); gated
        and PR-shipped like app onboarding, with the same strict admission on
        skipped app-side conformance legs (`allow_bootstrap` waives it). No
        secret step is yours.
        """
        try:
            result = await run_serialized(
                lambda: container.onboard_database().execute(
                    name=name, allow_bootstrap=allow_bootstrap
                )
            )
        except ValidationFailedError as exc:
            raise ToolError(_rejection(exc)) from exc
        except UnverifiedLegsError as exc:
            raise ToolError(_bootstrap_refusal(exc)) from exc
        return map_onboarding_result(result).model_dump()

    @server.tool()
    async def onboard_identity(name: str, allow_bootstrap: bool = False) -> dict[str, object]:
        """Prepare an app's Keycloak realm grant as a pull request.

        Renders from the studio's canonical template into the app's team
        folder (per concern file): the generate-if-absent credential Job
        (mints keycloak-<app> in-cluster, ADR-034) plus the realm blocks (own
        realm named for the app, a realm-scoped admin, and the zero or more
        identity providers declared by the install); gated and
        PR-shipped like app onboarding, with the same strict admission on
        skipped app-side conformance legs (`allow_bootstrap` waives it). The
        PR checklist names the callback URL to register for each declared
        broker, using that broker's upstream OAuth application.
        """
        try:
            result = await run_serialized(
                lambda: container.onboard_identity().execute(
                    name=name, allow_bootstrap=allow_bootstrap
                )
            )
        except ValidationFailedError as exc:
            raise ToolError(_rejection(exc)) from exc
        except UnverifiedLegsError as exc:
            raise ToolError(_bootstrap_refusal(exc)) from exc
        return map_onboarding_result(result).model_dump()

    @server.tool()
    async def reconcile_identity(name: str, allow_bootstrap: bool = False) -> dict[str, object]:
        """Re-render an app's existing Keycloak realm grant as a pull request.

        The day-2 verb for a realm (ADR-045): a realm carries what it was
        rendered with until it is reconciled, so an install that declared a
        default broker after granting its realms, or named a login theme,
        brings each realm up to date here; onboard_identity refuses an app
        whose realm exists and reconcile_app never touches grant files. Renders
        the realm ConfigMap and its provisioning Job from the CURRENT canonical
        template and the install's CURRENT declaration (values.yaml
        defaultBrokers and identity.loginTheme.name, read off the deploy
        branch, never from the caller) and replaces them in place in the app's
        team folder: every user the branch admitted to the realm is carried
        across (the users list is the access allowlist), and nothing else in
        the folder is touched - the app-owned keycloak-<app> credential and the
        Job that mints it, the client, the host, the other grants. The rendered
        documents are byte-identical to a fresh onboarding's for the same
        declaration. Refuses before any branch is prepared when the branch
        already carries that render (AlreadyExistsError: nothing to reconcile,
        so a sweep over every realm opens a pull request only where something
        changed), and refuses an app with no realm (grant one with
        onboard_identity). Gated and PR-shipped like the onboarding, with the
        same strict admission on skipped app-side legs (`allow_bootstrap`
        waives it). The PR body says what changed and why, and its checklist
        names the callback URL to register with the IdP for each broker alias
        the realm did not previously carry - the one step outside git, and
        yours; an alias already brokered keeps its registration, because the
        alias fixes the callback path. A broker the install no longer declares
        stops being converged but is not deleted from Keycloak (providers apply
        no-delete); removing it is the realm admin's act.
        """
        try:
            result = await run_serialized(
                lambda: container.reconcile_identity().execute(
                    name=name, allow_bootstrap=allow_bootstrap
                )
            )
        except ValidationFailedError as exc:
            raise ToolError(_rejection(exc)) from exc
        except UnverifiedLegsError as exc:
            raise ToolError(_bootstrap_refusal(exc)) from exc
        except AlreadyExistsError as exc:
            raise ToolError(_typed_refusal(exc)) from exc
        return map_onboarding_result(result).model_dump()

    @server.tool()
    async def onboard_events(
        name: str, domains: list[str], allow_bootstrap: bool = False
    ) -> dict[str, object]:
        """Prepare an app's event-bus grant as a pull request.

        Renders from the studio's canonical template into the app's team folder
        (per concern file): a generate-if-absent Job that mints the app's own
        nkey seed in its own namespace and publishes only the derived public
        key, plus the signing Job that returns a NATS user JWT scoped to the
        domains named here. The seed never leaves the app's namespace, so the
        platform signs an assertion about a key it has never seen and holds no
        tenant credential.

        `domains` are the REF-Events domains this app OWNS and may publish under
        (for example ["platform"] for `com.foundry.platform.*` types), and at
        least one is required. Reading stays open across the whole event space:
        the grant scopes what an app may say, not what it may hear. One domain
        has exactly one owner, so naming a domain another app already publishes
        fails the install's conformance rather than quietly double-granting it.

        Gated and PR-shipped like app onboarding, with the same strict admission
        on skipped app-side conformance legs (`allow_bootstrap` waives it).
        """
        try:
            result = await run_serialized(
                lambda: container.onboard_events().execute(
                    name=name, domains=domains, allow_bootstrap=allow_bootstrap
                )
            )
        except ValidationFailedError as exc:
            raise ToolError(_rejection(exc)) from exc
        except UnverifiedLegsError as exc:
            raise ToolError(_bootstrap_refusal(exc)) from exc
        return map_onboarding_result(result).model_dump()

    @server.prompt(
        name="onboard-app",
        title="Onboard an app onto the install",
        description=(
            "The full onboarding runbook for an app, parametrized with live "
            "install-manifest facts. The install side ships as a PR via the "
            "onboard_app tool; everything in your own app repo (contract, "
            "deploy branch, secrets) you execute yourself."
        ),
    )
    async def onboard_app_prompt(app: str) -> str:
        """The onboarding runbook, parametrized with the install's live facts."""
        return await run_serialized(lambda: _onboarding_runbook(container, app))

    if container.pr_enabled:

        @server.tool()
        async def list_onboarding_prs() -> list[dict[str, object]]:
            """Return every pull request the studio has open, awaiting its merge.

            All four change families, not onboardings alone: an offboard, a
            reconcile, and a settings write each ship one the same way, and
            this is their only surface once the call that opened them has
            returned. Read the branch to tell them apart.
            """
            prs = await run_serialized(lambda: container.list_prs().execute())
            return [map_pr_info(pr).model_dump() for pr in prs]

        @server.tool()
        async def get_onboarding_pr(number: int) -> dict[str, object]:
            """Return one onboarding pull request: number, url, state, and merged.

            The merge-status signal an onboarding run polls: the platform
            repo's CI merges the PR moments after it opens (ADR-036), so poll
            this until it reports merged: true (a 30s interval, bounded) and
            never merge by hand. state alone cannot distinguish admission
            from abandonment; only merged can.
            """
            pr = await run_serialized(lambda: container.get_pr().execute(number=number))
            return map_pr_info(pr).model_dump()

        @server.tool()
        async def cancel_onboarding(branch: str) -> dict[str, object]:
            """Clear a change branch off the remote that no open pull request tracks.

            The way out when an act refuses with `onboarding branch already
            exists`. That refusal names which of two states the branch is in:
            a pull request is open against it (in flight toward its automated
            merge, ADR-036, so wait) or none is (the branch outlived its pull
            request, or a publish pushed it and could not open one at all, and
            it now blocks every re-run of that target). This verb resolves the
            second: pass the branch exactly as the refusal named it
            (`onboard/<app>`, `onboard/<app>-db`, `onboard/<app>-identity`,
            `offboard/<app>`, `reconcile/<app>`, `settings/<key>`) and the
            target is re-runnable again. It refuses any other branch, and
            refuses one an open pull request still tracks, since deleting that
            branch would close the pull request unmerged and lose the change.
            Deleting a branch the remote does not carry answers deleted:
            false rather than failing.
            """
            try:
                result = await run_serialized(
                    lambda: container.cancel_onboarding().execute(branch=branch)
                )
            except AppError as exc:
                raise ToolError(_typed_refusal(exc)) from exc
            return map_cancelled_change(result).model_dump()

        @server.tool()
        async def refresh_platform() -> dict[str, object]:
            """Pull the upstream deploy-branch head into the managed checkout."""
            await run_serialized(container.refresh_content().execute)
            return {"refreshed": True}

    return server


def _typed_refusal(exc: Exception) -> str:
    """A refusal that names its own error class, then states it.

    MCP flattens an exception to ``str(e)`` (mcp lowlevel ``_make_error_result``,
    via FastMCP's ``Error executing tool <name>: <e>``), so the type is lost on
    the wire while the HTTP surface next door maps that same type to a status
    code. A caller then has only prose to branch on, and prose is not a
    contract: the Console has to tell "this repository already exists, adopt
    it" from "the scaffold failed halfway, refuse" - two outcomes with the same
    shape and opposite handling. Leading with the class name gives it the one
    stable token it can match, until the internal REST door carries the status
    itself (foundry-console#42).
    """
    return f"{type(exc).__name__}: {exc}"


def _rejection(exc: ValidationFailedError) -> str:
    report = exc.report
    return (
        "onboarding rejected by the conformance gates (rolled back).\n"
        f"new failures: {', '.join(exc.new_failures)}\n"
        f"suite: {report.passed} passed, {report.failed} failed, "
        f"{report.skipped} skipped (exit {report.exit_code})\n"
        f"{report.output}"
    )


def _bootstrap_refusal(exc: UnverifiedLegsError) -> str:
    report = exc.report
    return (
        f"onboarding refused (rolled back): {exc}\n"
        f"suite: {report.passed} passed, {report.failed} failed, "
        f"{report.skipped} skipped (exit {report.exit_code})\n"
        f"{report.output}"
    )


def _onboarding_runbook(container: Container, app: str) -> str:
    """Compose the runbook from live install facts (the client-executes idiom)."""
    import re

    if not re.match(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$", app):
        raise InvalidAppNameError(app)
    apps = container.list_apps().execute()
    declared = next((a for a in apps if a.entry.name == app), None)
    onboarded_names = [a.entry.name for a in apps if a.manifest is not None]
    reference = next(
        (a for a in apps if a.manifest is not None and a.manifest.hostname), None
    )
    domain = (
        reference.manifest.hostname.split(".", 1)[1]
        if reference and reference.manifest and "." in reference.manifest.hostname
        else "<platform domain>"
    )
    org = "<github org>"
    if reference and reference.manifest and "github.com/" in reference.manifest.repo_url:
        org = reference.manifest.repo_url.split("github.com/", 1)[1].split("/", 1)[0]
    deploy_branch = next(
        (
            a.manifest.target_revision
            for a in (declared, reference)
            if a is not None and a.manifest is not None and a.manifest.target_revision
        ),
        "deploy-<install>",
    )

    if declared is not None:
        missing_folder = (
            ", but its teams/ folder is missing. Check list_onboarding_prs "
            "for a PR still pending its automated merge; one sitting open means "
            "the platform repo's auto-merge run failed (read that run, ADR-036)."
            if container.pr_enabled
            else ", but its teams/ folder is missing. This composition manages "
            "no clone and opens no PRs: the onboarding lands in the working "
            "tree, so a missing folder means a half-applied checkout; review "
            "the working tree and re-run the onboard_app tool."
        )
        platform_step = (
            f"1. Install side: `{app}` is already declared in the install manifest"
            + (
                " and has a teams/ folder - the install side is done."
                if declared.manifest is not None
                else missing_folder
            )
        )
    else:
        shipping = (
            "It opens a pull "
            "request against the install's deploy branch; the platform repo's CI "
            "merges it moments after it opens (ADR-036), admitting the app and "
            f"granting the hostname `{app}.{domain}`. Never merge it yourself: "
            "poll get_onboarding_pr with the PR number every 30s until it "
            "reports merged: true, giving up after 10 minutes (about 20 "
            "polls). If it never reports merged, stop degraded and read the "
            "platform repo's auto-merge run (ADR-036) rather than retrying or "
            "merging by hand. Do not edit the platform repo "
            "yourself."
            if container.pr_enabled
            else "This composition manages no clone, so no pull request "
            "opens: the vetted change is left in the platform checkout's "
            "working tree for the operator to review and commit to the "
            "deploy branch, admitting the app and granting the hostname "
            f"`{app}.{domain}`; there is no PR to poll. Do not edit the "
            "platform repo beyond committing what the tool prepared."
        )
        platform_step = (
            f"1. Install side: call the onboard_app tool "
            f"(name='{app}', display_name, description, icon, expose_mcp if the app "
            "serves /mcp, role='parts' only for a Foundry tool, image_components "
            "naming the released images when CI publishes more than one - e.g. "
            "['server', 'client', 'docs'] binds one Image Updater alias per "
            f"package <registry>/{app}-<component> to "
            f"{app}.images.<component>.tag; empty means the single-image shape). "
            "Admission is strict: app-side conformance legs that cannot be "
            "read (the repo's build.yml, the deploy branch, the image "
            "bindings) refuse the onboarding naming each skipped leg; stand "
            "those artifacts up first, or pass allow_bootstrap=true for a "
            "deliberate walking-skeleton bootstrap (the waiver is recorded "
            "in the PR body). " + shipping
        )

    return f"""Onboard the app '{app}' onto the home-lab platform ({domain}).

The install side ships as a PR through this server; everything in the app's own
repo is team-owned and you execute it yourself, in that repo.

{platform_step}

2. App-repo contract (in your app repo, on main): devops/Dockerfile (one
   multi-stage image) + devops/docker-compose.yml building FROM it; k8s/ as a
   Helm chart (Chart.yaml, values.yaml, templates/) whose wiring the
   conformance suite pins (INT-FOUNDRY-045..047): every Deployment mounts
   imagePullSecrets (default ghcr-pull); the app HTTPRoute parentRefs the
   app's OWN Gateway (name={app}, namespace=network - never an invented one)
   and carries the app hostname, because external-dns registers DNS from the
   route; third-party sidecar images are pinned, never :latest; docs/ as a deployable
   Starlight site honoring DOCS_BASE=/apps/{app}; README.md with 'Run with
   Docker', 'Develop without Docker', 'Layout' sections; .env.example;
   intent.yaml (CSD-INTENT-01) plus docs/intent.yaml (STARLIGHT bundle);
   .pre-commit-config.yaml with a Conventional-Commits commit-msg hook;
   .github/workflows/build.yml calling the shared {org} CI workflow.

3. Pull secret: nothing to do. network/ghcr-pull auto-reflects into every
   namespace (reflection-auto-namespaces=.*, INT-FOUNDRY-044), so the app's
   namespace receives it on creation; no per-app step exists.

4. Secrets, by class (ADR-034): credentials the platform provisions against
   (pg-app-{app}, keycloak-{app}) are minted in-cluster by the database and
   identity grants themselves; do NOT author or apply them. Pure-random
   runtime secrets can also be granted a generate-if-absent block. A
   machine-door Basic key the app hands to a signed-in person through its
   own route (/api/agent-credential, feeding a Connect agent panel) is
   generated too, by the app's own chart: a generate-if-absent Sync-hook Job,
   its RBAC reaching only that Secret, runs ahead of the Deployment, which
   reads the Secret by required reference; the chart names that Secret
   itself (not auth.existingSecret) and ships no .env.example for it. Only a
   value the cluster cannot generate (an external fact: SMTP creds, a PAT) is
   seeded: set auth.existingSecret in k8s/values.yaml, fail closed (503 until
   the Secret exists), commit the k8s/secrets/<name>.env.example template,
   and the maintainer applies the real value out of band with
   seed/apply-secrets.sh; it never enters git.

5. After the onboarding lands on the deploy branch and CI first publishes
   the chart: create the `{deploy_branch}` orphan branch in the app repo,
   with one folder per environment the install declares, each holding a
   values.yaml plus a Chart.yaml pinning a published
   chart version from oci://<the install's registry>/charts. ArgoCD watches
   this branch (the rendered Application's targetRevision names it); Image
   Updater advances image tags on the entry environment's values automatically, chart
   version bumps stay manual.

6. Verify: read the app_status tool for '{app}'. It reports the whole
   evidence chain typed - onboarded, onboarding_pr, app_repo (the ci-caller
   row: build.yml calls the shared {org} CI workflow, INT-FOUNDRY-013; the
   deploy-branch row: `{deploy_branch}` carries one env-config folder per
   environment the install declares, and no others, INT-FOUNDRY-020; the
   image-updater bindings), ci, promotion,
   credentials (every platform-minted credential the chart names has the
   grant in teams/{app}/ that mints it, INT-GRANT-004; a failed one is why
   a pod sits in CreateContainerConfigError - run the matching grant),
   probe, identity_caveat - plus a derived stage. Poll it until the stage
   reads serving, and probe by hand ONLY the links the tool marks skipped
   (each skip names its reason); a skipped link means that leg is not yet
   verifiable, never a pass. The app-repo legs are read off the repo host,
   so they flip as you complete steps 2 and 5. Onboarded apps for
   reference: {", ".join(onboarded_names) or "none yet"}.

A database, if the app needs one, is a separate grant: the onboard_database
tool prepares that PR."""
