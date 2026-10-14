"""Use case: re-render an app's team folder against its fresh declaration."""

from __future__ import annotations

import re

from studio.application.ports.outbound.platform_repository import PlatformRepository
from studio.application.services.gated_change import GatedChange
from studio.application.services.pr_body import (
    advisory_section,
    changed_files_section,
    conformance_section,
    delivery_section,
)
from studio.domain.exceptions.entity_not_found_error import EntityNotFoundError
from studio.domain.exceptions.invalid_image_component_error import InvalidImageComponentError
from studio.domain.exceptions.invalid_repo_name_error import InvalidRepoNameError
from studio.domain.model.conformance_report import ConformanceReport
from studio.domain.model.onboarding_result import OnboardingResult
from studio.domain.services.change_branch import reconcile_branch
from studio.domain.services.environments import entry_environment
from studio.domain.services.image_promotion import PROMOTION_MANUAL, invalid_image_components
from studio.domain.services.team_documents import (
    freeze_application_promotion,
    pause_application,
)
from studio.domain.services.team_skeleton import (
    APP_REPO_ORG,
    SKELETON_FILE_ORDER,
    render_team_skeleton,
)
from studio.logging import get_logger

__all__ = ["ReconcileApp"]

logger = get_logger(__name__)

_REPO_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_APPLICATION_FILE = "application.yaml"


class ReconcileApp:
    """Implements ReconcileAppPort: the day-2 verb onboarding never had.

    Onboarding freezes a declaration into the rendered folder; conformance
    thereafter judges a moving truth (the app's released set) against that
    frozen declaration, and the only repair used to be an offboard-and-hope
    round trip that pruned the app's namespace on the way. Reconcile
    re-renders the five skeleton files from the current canonical templates
    and the caller's fresh ``image_components`` declaration - the accountable
    re-declaration, aligned with a platform manager, that the shared ci
    workflow's conformance check points teams at. Grant files are never
    touched: a database or identity grant is a separate onboarding's output
    and survives every reconcile. That holds because the two file sets are
    disjoint (INT-SKELETON-001), not because reconcile is careful -- it
    replaces every file it writes wholesale, so a grant document sharing a
    skeleton file is deleted, which is how reconciling solveos took the
    gen-pg-app-solveos Role and RoleBinding out from under a live generator
    Job (foundry-platform#100). The manifest entry is refreshed in place
    (same role, same mcp flag, same repository; the description written in),
    so the manifest stays the single source of the tile facts the platform
    chart renders. The app's lifecycle toggles carry over too: the canonical
    Application is neither frozen nor paused, so a frozen app gets the freeze
    tag filter on every alias the fresh declaration names, new ones included,
    and a paused app keeps its scale-to-zero override (ADR-008).
    """

    def __init__(
        self,
        repository: PlatformRepository,
        gated_change: GatedChange,
    ) -> None:
        self._repository = repository
        self._gated_change = gated_change

    def execute(
        self,
        *,
        name: str,
        image_components: tuple[str, ...] = (),
        description: str = "",
        repo: str = "",
        allow_bootstrap: bool = False,
    ) -> OnboardingResult:
        entry = next(
            (e for e in self._repository.manifest_entries() if e.name == name), None
        )
        if entry is None:
            raise EntityNotFoundError("app", name)
        if not self._repository.team_files(name):
            raise EntityNotFoundError("team folder", name)
        if repo and not _REPO_NAME.match(repo):
            raise InvalidRepoNameError(repo)
        bad_components = invalid_image_components(image_components)
        if bad_components:
            raise InvalidImageComponentError(bad_components)

        manifest = self._repository.team_manifest(name)
        # Current facts, manifest entry first (the single source), the team
        # folder's annotations as the fallback for apps authored before the
        # tile facts moved into the manifest.
        display = entry.display or (manifest.display_name if manifest else "") or name
        desc = (
            description
            or entry.description
            or (manifest.description if manifest else "")
        )
        icon = entry.icon or (manifest.icon if manifest else "")
        expose_mcp = entry.mcp_url is not None
        repo_name = (
            repo
            or entry.repo
            or self._repo_name(manifest.repo_url if manifest else "")
            or name
        )

        org = self._repository.organisation().org_or(APP_REPO_ORG)
        skeleton = render_team_skeleton(
            app=name,
            zone=self._repository.zone(),
            tunnel_id=self._repository.tunnel_id(),
            install=self._repository.install(),
            operators=self._repository.operators(),
            entry_env=entry_environment(self._repository.environments()),
            image_components=image_components,
            repo=repo_name,
            registry=self._repository.registry().prefix_or_ghcr(org),
            org=org,
        )

        carried: list[str] = []

        def mutate() -> None:
            # The toggles as the branch carries them, read off the checkout
            # the change is based on, before the render replaces them.
            current = self._repository.team_manifest(name)
            frozen = current is not None and current.promotion == PROMOTION_MANUAL
            paused = current is not None and current.paused
            # Refresh the entry in place: remove + re-insert lands in the same
            # sorted position, now carrying the description and the repository
            # the folder was rendered against (a `repo:` line only when it
            # differs from the name).
            self._repository.remove_manifest_entry(name)
            self._repository.add_manifest_entry(
                name=name, display=display, icon=icon, mcp=expose_mcp, role=entry.role,
                description=desc, repo=repo_name,
            )
            for filename, text in skeleton:
                if filename == _APPLICATION_FILE:
                    if frozen:
                        text = freeze_application_promotion(text, app=name)
                        carried.append("kept frozen: every alias carries the freeze tag filter")
                    if paused:
                        text = pause_application(text, app=name)
                        carried.append("kept paused: the scale-to-zero override carries over")
                self._repository.write_team_file(name, filename, text)

        touched = ("foundry.yaml",) + tuple(
            f"teams/{name}/{f}" for f in SKELETON_FILE_ORDER
        )
        logger.info(
            "Reconciling %s (components=%s, repo=%s)",
            name,
            list(image_components) or "single-image",
            repo_name,
        )
        return self._gated_change.execute(
            app=name,
            branch=reconcile_branch(name),
            touched_paths=touched,
            mutate=mutate,
            commit_message=f"fix(teams): reconcile {name}",
            pr_title=f"fix(teams): reconcile {name}",
            pr_body=lambda baseline, report, changed: self._pr_body(
                name=name,
                image_components=image_components,
                carried=tuple(carried),
                baseline=baseline,
                report=report,
                changed=changed,
            ),
            allow_bootstrap=allow_bootstrap,
        )

    @staticmethod
    def _repo_name(repo_url: str) -> str:
        match = re.search(r"github\.com[:/][^/]+/([^/]+?)(?:\.git)?/?$", repo_url)
        return match.group(1) if match else ""

    def _pr_body(
        self,
        *,
        name: str,
        image_components: tuple[str, ...],
        carried: tuple[str, ...],
        baseline: ConformanceReport,
        report: ConformanceReport,
        changed: tuple[str, ...],
    ) -> str:
        if image_components:
            packages = ", ".join(f"`{name}-{c}`" for c in image_components)
        else:
            packages = f"`{name}` (single-image shape)"
        summary = "\n".join(
            [
                f"Reconcile of `{name}`, prepared by platform-studio:",
                "- the five skeleton files re-rendered from the CURRENT canonical "
                "templates (canon refresh) and the caller's fresh declaration",
                f"- Image Updater now watches one alias per released image: {packages}",
                "- grant files (jobs, serviceaccounts, grant RBAC, realm config) "
                "untouched: a grant is a separate onboarding's output and survives "
                "reconcile, because no grant file is a skeleton file",
                "- the manifest entry refreshed in place, description included: the "
                "manifest is the single source of the tile facts",
                *(f"- {line}" for line in carried),
            ]
        )
        return "\n\n".join(
            section
            for section in (
                f"## Reconcile {name}",
                summary,
                changed_files_section(changed),
                conformance_section(baseline, report),
                delivery_section(name, report),
                advisory_section(name, report),
            )
            if section
        )
