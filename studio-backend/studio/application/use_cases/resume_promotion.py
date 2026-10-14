"""Use case: resume a frozen app's image promotion."""

from __future__ import annotations

from studio.application.ports.outbound.event_publisher import EventPublisher
from studio.application.ports.outbound.git_pr import GitPr
from studio.application.ports.outbound.platform_repository import PlatformRepository
from studio.application.services.event_types import PROMOTION_RESUMED, state_fact
from studio.domain.exceptions.entity_not_found_error import EntityNotFoundError
from studio.domain.model.platform_app import PlatformApp
from studio.domain.services.team_documents import resume_application_promotion
from studio.logging import get_logger

__all__ = ["ResumePromotion"]

logger = get_logger(__name__)

_APPLICATION_FILE = "application.yaml"


class ResumePromotion:
    """Implements ResumePromotionPort: drop the freeze tag filters, commit directly.

    Resuming removes only the lines the freeze wrote, restoring
    teams/<app>/application.yaml byte-for-byte to its promoting form, and
    direct-commits it to the install's deploy branch (ADR-008). Image Updater
    then promotes the newest released tag on its next pass, so the app catches
    up to whatever CI published while it was held.

    Resuming an app that is not frozen is an idempotent no-op.
    """

    def __init__(
        self,
        repository: PlatformRepository,
        git: GitPr,
        events: EventPublisher | None = None,
    ) -> None:
        self._repository = repository
        self._git = git
        self._events = events

    def execute(self, *, name: str) -> PlatformApp:
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
        promoting = resume_application_promotion(text, app=name)
        if promoting == text:
            return PlatformApp(entry=entry, manifest=self._repository.team_manifest(name))
        self._repository.write_team_file(name, _APPLICATION_FILE, promoting)
        self._git.commit_to_deploy(
            paths=(f"teams/{name}/{_APPLICATION_FILE}",),
            commit_message=f"chore(lifecycle): resume promotion for {name}",
        )
        logger.info("Resumed promotion for %s (tag filters removed, direct commit)", name)
        # The commit is on the branch before the fact is stated; an app that was
        # not frozen returned above and narrates nothing.
        state_fact(
            self._events,
            event_type=PROMOTION_RESUMED,
            subject=name,
            data={"app": name},
        )
        return PlatformApp(entry=entry, manifest=self._repository.team_manifest(name))
