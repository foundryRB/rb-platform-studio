"""Use case: tune a curated platform setting, conformance-gated, PR-mode."""

from __future__ import annotations

from studio.application.ports.outbound.event_publisher import EventPublisher
from studio.application.ports.outbound.platform_repository import PlatformRepository
from studio.application.services.event_types import SETTING_CHANGED, pr_pointer, state_fact
from studio.application.services.gated_change import GatedChange
from studio.application.services.pr_body import changed_files_section, conformance_section
from studio.domain.exceptions.already_exists_error import AlreadyExistsError
from studio.domain.exceptions.entity_not_found_error import EntityNotFoundError
from studio.domain.exceptions.invalid_setting_value_error import InvalidSettingValueError
from studio.domain.model.conformance_report import ConformanceReport
from studio.domain.model.onboarding_result import OnboardingResult
from studio.domain.services.change_branch import setting_branch
from studio.domain.services.platform_settings import (
    VALUES_FILE,
    CuratedSetting,
    build_setting,
    find_setting,
    set_value,
    validation_error,
)
from studio.logging import get_logger

__all__ = ["UpdatePlatformSetting"]

logger = get_logger(__name__)


class UpdatePlatformSetting:
    """Implements UpdatePlatformSettingPort: write one knob into the install's values.

    A platform setting is tuned the way a hostname is granted: the change lands
    on a branch off the install's deploy branch, the conformance gate judges the
    whole candidate state, and the merge is the admission act performed by the
    platform repo's CI (ADR-036). It is never a direct commit, which separates
    it from the lifecycle toggles (pause/resume): those admit no state a gate
    could disagree with, whereas a retention horizon reconciles into a running
    component's config.

    The write carries the value only. The installed chart must bind the field
    to `.Values` before the setting can take effect. Once it does, ArgoCD
    reconciles the deploy branch's values.yaml on the next sync.
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

    def execute(self, *, key: str, value: str) -> OnboardingResult:
        curated = find_setting(key)
        if curated is None:
            raise EntityNotFoundError("platform setting", key)
        candidate = value.strip()
        problem = validation_error(curated, candidate)
        if problem is not None:
            raise InvalidSettingValueError(key, problem)

        current = build_setting(curated, self._repository.raw_read(VALUES_FILE))
        if current.value == candidate:
            raise AlreadyExistsError(
                "platform setting value", f"{key} is already set to {candidate}"
            )

        def mutate() -> None:
            existing = self._repository.raw_read(VALUES_FILE)
            if existing is None:
                raise EntityNotFoundError(VALUES_FILE, "the install's deploy branch")
            self._repository.raw_write(
                VALUES_FILE, set_value(existing, curated.path, candidate)
            )

        logger.info(
            "Tuning %s: %s -> %s (%s)",
            key,
            current.effective,
            candidate,
            "was the chart default" if current.value is None else "was set on the branch",
        )
        result = self._gated_change.execute(
            app=key,
            branch=setting_branch(key),
            touched_paths=(VALUES_FILE,),
            mutate=mutate,
            commit_message=f"chore(settings): set {curated.field} to {candidate}",
            pr_title=f"chore(settings): {curated.label.lower()} -> {candidate}",
            pr_body=lambda baseline, report, changed: self._pr_body(
                curated=curated,
                previous=current.effective,
                pinned=current.value is not None,
                candidate=candidate,
                baseline=baseline,
                report=report,
                changed=changed,
            ),
        )
        # The setting's pull request is open before the fact is stated. The
        # value is the fact itself (a retention horizon, never a secret), so it
        # rides along with the pointer.
        state_fact(
            self._events,
            event_type=SETTING_CHANGED,
            subject=key,
            data={
                "setting": key,
                "value": candidate,
                "previous": current.effective,
                "branch": result.branch,
                "pr": pr_pointer(result.pr),
            },
        )
        return result

    def _pr_body(
        self,
        *,
        curated: CuratedSetting,
        previous: str,
        pinned: bool,
        candidate: str,
        baseline: ConformanceReport,
        report: ConformanceReport,
        changed: tuple[str, ...],
    ) -> str:
        origin = (
            f"`{previous}` (set on the deploy branch)"
            if pinned
            else f"`{previous}` (the chart default; the branch pinned nothing)"
        )
        summary = "\n".join(
            [
                f"Platform setting tuned by platform-studio: **{curated.label}**.",
                "",
                f"- `{curated.field}` in `{VALUES_FILE}`: {origin} -> `{candidate}`",
                f"- {curated.description}",
                "- Value only: no chart pin moves. The installed chart must read "
                "this field from `.Values` for ArgoCD to apply the new value "
                "on its next sync.",
            ]
        )
        if curated.unit == "count":
            checklist = "\n".join(
                [
                    "### Before merging",
                    "",
                    f"- [ ] `{candidate}` fits this install's runner capacity",
                    "- [ ] The installed platform chart reads this setting from `.Values`",
                ]
            )
        else:
            checklist = "\n".join(
                [
                    "### Before merging",
                    "",
                    f"- [ ] `{candidate}` is the horizon intended for {curated.label.lower()}",
                    "- [ ] The component's PVC can hold it. `local-path` volumes cannot "
                    "expand in place, so a horizon raised past what its claim holds is a "
                    "re-provisioned PVC, not a value edit - the pod fills its disk instead.",
                ]
            )
        return "\n\n".join(
            section
            for section in (
                f"## {curated.label} -> {candidate}",
                summary,
                changed_files_section(changed),
                conformance_section(baseline, report),
                checklist,
            )
            if section
        )
