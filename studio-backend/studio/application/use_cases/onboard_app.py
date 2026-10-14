"""Use case: install-side app onboarding, conformance-gated, PR-mode."""

from __future__ import annotations

import re

from studio.adapters.outbound.events import LoggingEventPublisher
from studio.application.ports.outbound.app_repo_source import AppRepoSource
from studio.application.ports.outbound.app_repo_writer import AppRepoWriter
from studio.application.ports.outbound.event_publisher import EventPublisher
from studio.application.ports.outbound.platform_repository import PlatformRepository
from studio.application.services.event_types import APP_ONBOARDED, pr_pointer, state_fact
from studio.application.services.gated_change import GatedChange
from studio.application.services.pr_body import (
    advisory_section,
    changed_files_section,
    conformance_section,
    delivery_section,
)
from studio.domain.exceptions.already_exists_error import AlreadyExistsError
from studio.domain.exceptions.entity_not_found_error import EntityNotFoundError
from studio.domain.exceptions.invalid_app_name_error import InvalidAppNameError
from studio.domain.exceptions.invalid_image_component_error import InvalidImageComponentError
from studio.domain.exceptions.invalid_repo_name_error import InvalidRepoNameError
from studio.domain.exceptions.invalid_role_error import InvalidRoleError
from studio.domain.model.conformance_report import ConformanceReport
from studio.domain.model.onboarding_result import OnboardingResult
from studio.domain.services.change_branch import onboard_branch
from studio.domain.services.deploy_branch import render_deploy_branch
from studio.domain.services.environments import entry_environment
from studio.domain.services.image_promotion import invalid_image_components
from studio.domain.services.team_skeleton import APP_REPO_ORG, render_team_skeleton
from studio.logging import get_logger

__all__ = ["OnboardApp"]

logger = get_logger(__name__)

_DNS_LABEL = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
# A repository name under the org, in the repo host's own alphabet: an app
# name is a DNS label because it becomes a namespace and a hostname, and a
# repo name becomes neither.
_REPO_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_ROLES = ("parts", "output")


class OnboardApp:
    """Implements OnboardAppPort: manifest entry, canonical team folder, gate.

    The studio prepares and validates the admission artifacts of an
    install onboarding (platform ADR-032): the app's entry in foundry.yaml and its
    teams/<app>/ folder, RENDERED from the studio's canonical skeleton templates
    keyed on the install's own facts (zone, tunnel, operators, deploy branch),
    not copied from a donor app. Admitting the app (merging the PR into the
    deploy branch) is the platform repo CI's act (platform ADR-036); everything
    team-owned (the app repo's deploy-<install> branch, secrets) stays with
    the team and the onboard-app runbook.
    Manifest-derived views (dashboards, homepage, docs index) are rendered by
    the platform chart on sync; the onboarding writes no derived file.
    """

    def __init__(
        self,
        repository: PlatformRepository,
        gated_change: GatedChange,
        app_repo: AppRepoSource | None = None,
        app_writer: AppRepoWriter | None = None,
        events: EventPublisher | None = None,
    ) -> None:
        self._repository = repository
        self._gated_change = gated_change
        # A publisher is always present; without a bus grant it states facts to
        # the log, so the act's outcome is identical either way.
        self._events = events or LoggingEventPublisher()
        # The deploy-branch bootstrap: with a reader (to see the branch is
        # absent) and a writer (the fleet write credential) wired, the
        # onboarding stands the app's deploy-<install> branch up itself,
        # deterministically, from the declaration plus the latest published
        # chart and image tags on GHCR. Without either, the branch stays the
        # runbook's step 5, exactly as before.
        self._app_repo = app_repo
        self._app_writer = app_writer

    def execute(
        self,
        *,
        name: str,
        display_name: str,
        description: str,
        icon: str,
        expose_mcp: bool,
        role: str = "output",
        image_components: tuple[str, ...] = (),
        repo: str = "",
        allow_bootstrap: bool = False,
    ) -> OnboardingResult:
        if not _DNS_LABEL.match(name):
            raise InvalidAppNameError(name)
        if repo and not _REPO_NAME.match(repo):
            raise InvalidRepoNameError(repo)
        if role not in _ROLES:
            raise InvalidRoleError(role)
        bad_components = invalid_image_components(image_components)
        if bad_components:
            raise InvalidImageComponentError(bad_components)
        if any(entry.name == name for entry in self._repository.manifest_entries()):
            raise AlreadyExistsError("app", name)
        if self._repository.team_files(name):
            raise AlreadyExistsError("team folder", name)

        zone = self._zone()
        environments = self._repository.environments()
        org = self._repository.organisation().org_or(APP_REPO_ORG)
        registry_prefix = self._repository.registry().prefix_or_ghcr(org)
        skeleton = render_team_skeleton(
            app=name,
            zone=zone,
            tunnel_id=self._repository.tunnel_id(),
            install=self._repository.install(),
            operators=self._repository.operators(),
            entry_env=entry_environment(environments),
            image_components=image_components,
            repo=repo,
            registry=registry_prefix,
            org=org,
        )
        mcp_url = f"https://{name}.{zone}/mcp" if expose_mcp else None
        deploy_branch_created = self._ensure_deploy_branch(
            name=name,
            repo=repo or name,
            image_components=image_components,
            zone=zone,
            environments=environments,
            org=org,
        )

        def mutate() -> None:
            self._repository.add_manifest_entry(
                name=name, display=display_name, icon=icon, mcp=expose_mcp, role=role,
                description=description, repo=repo,
            )
            for filename, text in skeleton:
                self._repository.write_team_file(name, filename, text)

        touched = ("foundry.yaml",) + tuple(f"teams/{name}/{f}" for f, _ in skeleton)
        logger.info(
            "Onboarding %s from repo %s (rendered, role=%s, mcp=%s)",
            name,
            repo or name,
            role,
            expose_mcp,
        )
        result = self._gated_change.execute(
            app=name,
            branch=onboard_branch(name),
            touched_paths=touched,
            mutate=mutate,
            commit_message=f"feat(teams): onboard {name}",
            pr_title=f"feat(teams): onboard {name}",
            pr_body=lambda baseline, report, changed: self._pr_body(
                name=name,
                zone=zone,
                role=role,
                mcp_url=mcp_url,
                repo=repo or name,
                image_components=image_components,
                deploy_branch_created=deploy_branch_created,
                baseline=baseline,
                report=report,
                changed=changed,
            ),
            allow_bootstrap=allow_bootstrap,
        )
        # The onboarding has landed (or its pull request is open) before the fact
        # is stated. A consumer treats this as a hint and reads the branch for
        # the truth, so the event carries identity and pointers, never the
        # rendered manifest (REF-Events section 5).
        state_fact(
            self._events,
            event_type=APP_ONBOARDED,
            subject=name,
            data={"app": name, "branch": result.branch, "pr": pr_pointer(result.pr)},
        )
        return result

    def _ensure_deploy_branch(
        self,
        *,
        name: str,
        repo: str,
        image_components: tuple[str, ...],
        zone: str,
        environments: tuple[str, ...],
        org: str,
    ) -> bool:
        """Stand up the app's deploy-<install> branch when absent and possible.

        Deterministic and fail-safe: only with both the reader and the writer
        wired, only when the branch does not exist, and only when the latest
        published chart and every released image's latest tag are readable
        off the install's registry. Anything unreadable leaves the branch to
        the runbook (the gate's strict admission on the deploy-branch leg is
        unchanged), and an existing branch is never touched. The tag read is
        the GHCR packages API - the one implementation of the registry read
        (platform ADR-044, #164) - so an install declaring another registry is told so
        explicitly and left to the runbook, never silently asked GHCR.
        """
        if self._app_writer is None or self._app_repo is None:
            return False
        install = self._repository.install()
        if not install:
            return False
        registry = self._repository.registry()
        if registry.declared and registry.host != "ghcr.io":
            logger.info(
                "Deploy branch for %s left to the runbook: this install's registry is "
                "%s and the studio's registry read is implemented for ghcr.io only; "
                "seed the branch with tags read from that registry by hand",
                name,
                registry.host,
            )
            return False
        repo_url = f"https://github.com/{org}/{repo}"
        branch = f"deploy-{install}"
        if self._app_repo.branch_paths(repo_url=repo_url, branch=branch) is not None:
            return False  # stood up already; the team owns it from here
        chart_version = self._app_writer.latest_semver_tag(owner=org, package=f"charts/{name}")
        packages = (
            [name] if not image_components else [f"{name}-{c}" for c in image_components]
        )
        image_tags: dict[str, str] = {}
        for package in packages:
            tag = self._app_writer.latest_semver_tag(owner=org, package=package)
            if tag:
                image_tags[package] = tag
        if not chart_version or len(image_tags) != len(packages):
            logger.info(
                "Deploy branch for %s left to the runbook: chart or image tags "
                "unreadable off GHCR (chart=%s, tags=%s/%s); CI must publish first",
                name,
                chart_version,
                len(image_tags),
                len(packages),
            )
            return False
        files = dict(
            render_deploy_branch(
                app=name,
                registry=registry.prefix_or_ghcr(org),
                components=image_components,
                chart_version=chart_version,
                image_tags=image_tags,
                zone=zone,
                environments=environments,
            )
        )
        created = self._app_writer.create_orphan_branch(
            repo_url=repo_url,
            branch=branch,
            files=files,
            message=f"chore(deploy): stand up {branch} (rendered by platform-studio)",
        )
        if created:
            logger.info(
                "Stood up %s on %s (chart %s)", branch, repo_url, chart_version
            )
        return created

    def _zone(self) -> str:
        zone = self._repository.zone()
        if "." not in zone:
            raise EntityNotFoundError("install zone", "values.yaml")
        return zone

    def _pr_body(
        self,
        *,
        name: str,
        zone: str,
        role: str,
        mcp_url: str | None,
        repo: str,
        image_components: tuple[str, ...],
        deploy_branch_created: bool,
        baseline: ConformanceReport,
        report: ConformanceReport,
        changed: tuple[str, ...],
    ) -> str:
        mcp_line = (
            f"- `mcp: true` on the manifest entry; the endpoint derives as `{mcp_url}`"
            if mcp_url
            else ""
        )
        if image_components:
            packages = ", ".join(f"`{name}-{c}`" for c in image_components)
            tag_paths = ", ".join(f"`{name}.images.{c}.tag`" for c in image_components)
        else:
            packages = f"`{name}`"
            tag_paths = f"`{name}.image.tag`"
        promotion_line = (
            f"- Image Updater watches one alias per released image ({packages}), "
            f"each bound to the values path its chart reads ({tag_paths})"
        )
        summary = "\n".join(
            line
            for line in (
                f"Install-side onboarding of `{name}`, prepared by platform-studio:",
                f"- manifest entry in `foundry.yaml` under `{role}`",
                f"- the Application points at the `{repo}` repository; `{name}` is the "
                "fleet name (namespace, hostname label, chart, GHCR packages)",
                f"- `teams/{name}/` rendered from the studio's canonical skeleton "
                "templates, keyed on this install's facts (zone, tunnel, operators, "
                "deploy branch)",
                f"- its homepage group is set from the `{role}` role "
                "(parts → Foundry, output → Apps)",
                mcp_line,
                promotion_line,
                "- dashboards, homepage bookmarks, and the docs index render from "
                "the manifest inside the platform chart on sync; nothing is "
                "generated into files",
            )
            if line
        )
        checklist = "\n".join(
            [
                "### Onboarding checklist",
                "",
                f"- [ ] Hostname grant intended: `{name}.{zone}`",
                f"- [ ] The app is delivered from the `{repo}` repository",
                "- [ ] App repo exists and meets the REF-Foundry app-repo contract",
                (
                    "- [x] The `deploy-<install>` branch was stood up by this "
                    "onboarding (rendered deterministically: latest published "
                    "chart pin, latest image tags; the team owns it from here)"
                    if deploy_branch_created
                    else "- [ ] After merge: the team stands up the "
                    "`deploy-<install>` branch (the `onboard-app` MCP prompt is "
                    "the runbook)"
                ),
                f"- [ ] That branch's entry environment values carry the tag path(s) the "
                f"Image Updater annotations write ({tag_paths}); the conformance "
                "row `install/promotion::image-updater-promotes` verifies the "
                "binding once the branch is readable",
                "- [ ] Only seeded secrets need a hand (platform ADR-034): the pull secret "
                "auto-reflects to every namespace, and platform-provisioned "
                "credentials are minted in-cluster by their grants; apply out of "
                "band only a `k8s/secrets/*.env.example` whose value the cluster "
                "cannot generate (an external fact)",
            ]
        )
        return "\n\n".join(
            section
            for section in (
                f"## Onboard {name}",
                summary,
                changed_files_section(changed),
                conformance_section(baseline, report),
                delivery_section(name, report),
                advisory_section(name, report),
                checklist,
            )
            if section
        )
