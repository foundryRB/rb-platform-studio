"""Use case: freeze an app's image promotion (hold it on its current version)."""

from __future__ import annotations

from studio.application.ports.outbound.event_publisher import EventPublisher
from studio.application.ports.outbound.git_pr import GitPr
from studio.application.ports.outbound.platform_repository import PlatformRepository
from studio.application.services.event_types import PROMOTION_FROZEN, state_fact
from studio.domain.exceptions.entity_not_found_error import EntityNotFoundError
from studio.domain.model.platform_app import PlatformApp
from studio.domain.services.team_documents import freeze_application_promotion
from studio.logging import get_logger

__all__ = ["FreezePromotion"]

logger = get_logger(__name__)

_APPLICATION_FILE = "application.yaml"


class FreezePromotion:
    """Implements FreezePromotionPort: add the freeze tag filters, commit directly.

    Freezing stops ArgoCD Image Updater promoting new image tags into the app's
    deploy branch, so the app keeps running the version it runs and a new
    release reaches it only when someone sets the tag by hand. Like pause it is
    an operational, reversible toggle that admits no app and grants no
    hostname, so it rides the direct-commit fast path (ADR-008) rather than a
    gated pull request.

    Unlike pause it is NOT refused for the studio's own app: freezing the
    studio holds it on its current version, which leaves the control plane
    running and able to unfreeze itself - the failure mode SelfPauseError
    exists for does not apply.

    Freezing an already-frozen app is an idempotent no-op: the toggle commits
    only when the edit actually changed the file, which also completes a
    partially frozen Application (a state only a hand edit produces).
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
        frozen = freeze_application_promotion(text, app=name)
        if frozen == text:
            return PlatformApp(entry=entry, manifest=self._repository.team_manifest(name))
        self._repository.write_team_file(name, _APPLICATION_FILE, frozen)
        self._git.commit_to_deploy(
            paths=(f"teams/{name}/{_APPLICATION_FILE}",),
            commit_message=f"chore(lifecycle): freeze promotion for {name}",
        )
        logger.info("Froze promotion for %s (tag filters added, direct commit)", name)
        # The commit is on the branch before the fact is stated; an already-frozen
        # app returned above and narrates nothing.
        state_fact(
            self._events,
            event_type=PROMOTION_FROZEN,
            subject=name,
            data={"app": name},
        )
        return PlatformApp(entry=entry, manifest=self._repository.team_manifest(name))
