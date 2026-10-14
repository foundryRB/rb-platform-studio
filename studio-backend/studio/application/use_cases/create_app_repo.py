"""Use case: create a templated app repository (the walking-skeleton scaffold)."""

from __future__ import annotations

import re

from studio.application.ports.outbound.app_repo_source import AppRepoSource
from studio.application.ports.outbound.app_repo_writer import AppRepoWriter
from studio.application.ports.outbound.platform_repository import PlatformRepository
from studio.domain.exceptions.already_exists_error import AlreadyExistsError
from studio.domain.exceptions.invalid_app_name_error import InvalidAppNameError
from studio.domain.exceptions.invalid_repo_name_error import InvalidRepoNameError
from studio.domain.exceptions.pr_failed_error import PrFailedError
from studio.domain.exceptions.sync_failed_error import SyncFailedError
from studio.domain.model.repo_scaffold_result import RepoScaffoldResult
from studio.domain.services.app_repo_scaffold import (
    SCAFFOLD_COMPONENTS,
    render_app_repo_scaffold,
)
from studio.domain.services.deploy_branch import render_deploy_branch
from studio.domain.services.team_skeleton import APP_REPO_ORG
from studio.logging import get_logger

__all__ = ["CreateAppRepo"]

logger = get_logger(__name__)

_DNS_LABEL = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
# The repository's own alphabet, matching onboard_app's: an app name is a DNS
# label because it becomes a namespace and a hostname; a repo name becomes
# neither, so it admits the wider set the repo host does.
_REPO_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")

# The version semantic-release cuts on a repo's first conventional push, and
# therefore the deterministic pin the scaffold's deploy branch carries.
_FIRST_RELEASE = "1.0.0"


class CreateAppRepo:
    """Implements CreateAppRepoPort: repo, scaffold, deploy branch, in order.

    The console's delivery flow used to create bare repos and leave the
    contract to skills authoring it by hand, drifting file by file; here the
    contract IS the template, rendered server-side from the same canonical
    source the conformance checks pin, so drift has nowhere to start. The
    deploy-<install> branch is stood up in the same act, pinned at the 1.0.0
    the first push releases - deterministic, because semantic-release's first
    cut is always 1.0.0 - which means onboard_app later finds every app-side
    leg already readable and admits without a waiver.

    Repo and scaffold succeed or fail together: a seed that cannot land takes
    the repository with it (see _rollback), because the one state no caller
    can detect from the outside is a repo that exists and looks new but
    carries none of the contract. The deploy branch is the deliberate
    exception - it is derived state a later onboard_app can stand up, so its
    failure is logged and the scaffold still counts.
    """

    def __init__(
        self,
        repository: PlatformRepository,
        app_repo: AppRepoSource | None = None,
        app_writer: AppRepoWriter | None = None,
    ) -> None:
        self._repository = repository
        self._app_repo = app_repo
        self._app_writer = app_writer

    def execute(
        self, *, name: str, display_name: str, description: str, repo: str = ""
    ) -> RepoScaffoldResult:
        if not _DNS_LABEL.match(name):
            raise InvalidAppNameError(name)
        if repo and not _REPO_NAME.match(repo):
            raise InvalidRepoNameError(repo)
        if self._app_writer is None or self._app_repo is None:
            raise SyncFailedError(
                "repo creation needs the fleet write credential "
                "(STUDIO_FLEET_WRITE_TOKEN) and the fleet reader wired; this "
                "composition has neither, so there is nothing to create with"
            )
        organisation = self._repository.organisation()
        org = organisation.org_or(APP_REPO_ORG)
        # The repository this app ships from, which is a fact separate from the
        # app's fleet name (INT-SKELETON-001) and defaults to it. An organisation
        # shared with other work prefixes its repositories while its apps keep
        # their own names, so the scaffold below is still rendered for `name` -
        # the chart, the packages, the namespace and the hostname are all the
        # app's - and only the repository it lands in is `repo_name`.
        repo_name = repo or name
        repo_url = f"https://github.com/{org}/{repo_name}"
        if self._app_repo.repo_exists(repo_url=repo_url):
            raise AlreadyExistsError("repository", repo_name)

        registry = self._repository.registry()
        files = render_app_repo_scaffold(
            app=name,
            display_name=display_name,
            description=description,
            registry=registry.prefix_or_ghcr(org),
            pull_secret=registry.pull_secret_or_ghcr(),
            org=org,
            ci_repo=organisation.ci_repo_or(),
        )
        if not self._app_writer.create_repository(
            org=org, name=repo_name, description=description
        ):
            raise PrFailedError(f"the repo host refused to create {org}/{repo_name}")
        if not self._app_writer.seed_branch(
            repo_url=repo_url,
            branch="main",
            files=files,
            message="feat: walking-skeleton scaffold (rendered by platform-studio)",
        ):
            # Atomic or nothing. A repo created and then left unseeded reads as a
            # perfectly ordinary new app to everything downstream - which is how one
            # once reached a delivery's build phase carrying no contract at all - so
            # the act undoes the repository it made rather than handing the caller a
            # half-built one to discover later.
            raise PrFailedError(self._rollback(org, repo_name))

        deploy_branch = ""
        install = self._repository.install()
        zone = self._repository.zone()
        if install and zone:
            branch = f"deploy-{install}"
            packages = {f"{name}-{c}": _FIRST_RELEASE for c in SCAFFOLD_COMPONENTS}
            branch_files = dict(
                render_deploy_branch(
                    app=name,
                    registry=registry.prefix_or_ghcr(org),
                    components=SCAFFOLD_COMPONENTS,
                    chart_version=_FIRST_RELEASE,
                    image_tags=packages,
                    zone=zone,
                    environments=self._repository.environments(),
                )
            )
            if self._app_writer.create_orphan_branch(
                repo_url=repo_url,
                branch=branch,
                files=branch_files,
                message=f"chore(deploy): stand up {branch} (rendered by platform-studio)",
            ):
                deploy_branch = branch
            else:
                logger.info(
                    "Scaffolded %s but could not stand up %s; the runbook step remains",
                    name,
                    branch,
                )

        logger.info(
            "Created %s (%d files, components=%s, deploy_branch=%s)",
            repo_url,
            len(files),
            list(SCAFFOLD_COMPONENTS),
            deploy_branch or "none",
        )
        return RepoScaffoldResult(
            name=name,
            repo_url=repo_url,
            branch="main",
            deploy_branch=deploy_branch,
            files=tuple(sorted(files)),
            image_components=SCAFFOLD_COMPONENTS,
        )

    def _rollback(self, org: str, name: str) -> str:
        """Undo the repository this act created after its seed failed; the
        refusal message, which tells the truth about what survived.

        A rollback that itself fails (a token without delete rights) must not
        read like a clean one: the caller is told the repository is still
        there and needs a hand, because the alternative is the silent
        half-built repo this whole path exists to prevent.

        The message carries the host's own refusal, because "retry" is only
        honest advice for a transient failure: a standing one (a credential
        missing a scope) refuses identically forever, and an operator who
        cannot see why retries instead of fixing it.
        """
        cause = self._app_writer.last_failure() if self._app_writer else ""
        because = f" ({cause})" if cause else ""
        if self._app_writer is None or not self._app_writer.delete_repository(
            org=org, name=name
        ):
            logger.info("Could not roll back %s/%s after a failed seed", org, name)
            return (
                f"created {org}/{name} but could not seed main{because}, and "
                "could not delete it either; the repository survives EMPTY - delete it "
                "by hand before retrying"
            )
        logger.info("Rolled back %s/%s after a failed seed", org, name)
        return (
            f"could not seed {org}/{name}{because}; the repository was "
            "removed again, so nothing was left behind"
        )
