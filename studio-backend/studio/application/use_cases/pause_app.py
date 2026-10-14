"""Use case: pause an app by scaling its workload to zero."""

from __future__ import annotations

from studio.application.ports.outbound.event_publisher import EventPublisher
from studio.application.ports.outbound.git_pr import GitPr
from studio.application.ports.outbound.platform_repository import PlatformRepository
from studio.application.services.event_types import APP_PAUSED, state_fact
from studio.domain.exceptions.entity_not_found_error import EntityNotFoundError
from studio.domain.exceptions.self_pause_error import SelfPauseError
from studio.domain.model.platform_app import PlatformApp
from studio.domain.services.team_documents import pause_application
from studio.logging import get_logger

__all__ = ["PauseApp"]

logger = get_logger(__name__)

_APPLICATION_FILE = "application.yaml"


class PauseApp:
    """Implements PauseAppPort: add the scale-to-zero override, commit it directly.

    Pausing scales an app to zero to free node capacity: an operational,
    reversible toggle, not an onboarding. It admits no app and grants no
    hostname, so it rides the direct-commit fast path to the install's deploy
    branch (ADR-008) rather than a gated pull request. The studio refuses to
    pause its own app, which would scale away the control plane that resumes
    it. Pausing an already-paused app is an idempotent no-op.
    """

    def __init__(
        self,
        repository: PlatformRepository,
        git: GitPr,
        self_app: str,
        events: EventPublisher | None = None,
    ) -> None:
        self._repository = repository
        self._git = git
        self._self_app = self_app
        self._events = events

    def execute(self, *, name: str) -> PlatformApp:
        if name == self._self_app:
            raise SelfPauseError(name)
        # Read and edit the deploy branch as it stands upstream, never a
        # stale clone (ADR-008).
        self._git.refresh()
        entry = next(
            (e for e in self._repository.manifest_entries() if e.name == name), None
        )
        if entry is None:
            raise EntityNotFoundError("app", name)
        text = self._repository.team_file_text(name, _APPLICATION_FILE)
        if text is None:
            raise EntityNotFoundError("team folder", name)
        manifest = self._repository.team_manifest(name)
        if manifest is not None and manifest.paused:
            return PlatformApp(entry=entry, manifest=manifest)
        self._repository.write_team_file(
            name, _APPLICATION_FILE, pause_application(text, app=name)
        )
        self._git.commit_to_deploy(
            paths=(f"teams/{name}/{_APPLICATION_FILE}",),
            commit_message=f"chore(lifecycle): pause {name}",
        )
        logger.info("Paused %s (scale-to-zero override, direct commit to the deploy branch)", name)
        # The commit is on the branch before the fact is stated; an already-paused
        # app returned above and narrates nothing.
        state_fact(
            self._events,
            event_type=APP_PAUSED,
            subject=name,
            data={"app": name},
        )
        return PlatformApp(entry=entry, manifest=self._repository.team_manifest(name))
