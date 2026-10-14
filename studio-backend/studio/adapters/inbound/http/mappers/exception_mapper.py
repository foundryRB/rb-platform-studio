"""Mapping from domain exceptions to HTTP status codes."""

from __future__ import annotations

from studio.domain.exceptions.already_exists_error import AlreadyExistsError
from studio.domain.exceptions.direct_commit_refused_error import DirectCommitRefusedError
from studio.domain.exceptions.entity_not_found_error import EntityNotFoundError
from studio.domain.exceptions.invalid_app_name_error import InvalidAppNameError
from studio.domain.exceptions.invalid_branch_error import InvalidBranchError
from studio.domain.exceptions.invalid_image_component_error import InvalidImageComponentError
from studio.domain.exceptions.invalid_repo_name_error import InvalidRepoNameError
from studio.domain.exceptions.invalid_role_error import InvalidRoleError
from studio.domain.exceptions.invalid_setting_value_error import InvalidSettingValueError
from studio.domain.exceptions.pause_conflict_error import PauseConflictError
from studio.domain.exceptions.pending_merge_error import PendingMergeError
from studio.domain.exceptions.pr_failed_error import PrFailedError
from studio.domain.exceptions.promotion_conflict_error import PromotionConflictError
from studio.domain.exceptions.promotion_unbound_error import PromotionUnboundError
from studio.domain.exceptions.self_offboard_error import SelfOffboardError
from studio.domain.exceptions.self_pause_error import SelfPauseError
from studio.domain.exceptions.sync_failed_error import SyncFailedError
from studio.domain.exceptions.unverified_legs_error import UnverifiedLegsError
from studio.domain.exceptions.validation_failed_error import ValidationFailedError

__all__ = ["STATUS_MAP", "DEFAULT_STATUS"]

STATUS_MAP: dict[type[Exception], int] = {
    AlreadyExistsError: 409,
    DirectCommitRefusedError: 409,
    EntityNotFoundError: 404,
    InvalidAppNameError: 400,
    InvalidBranchError: 400,
    InvalidImageComponentError: 400,
    InvalidRepoNameError: 400,
    InvalidRoleError: 400,
    InvalidSettingValueError: 400,
    PauseConflictError: 409,
    PendingMergeError: 409,
    PromotionConflictError: 409,
    PromotionUnboundError: 409,
    SelfOffboardError: 409,
    SelfPauseError: 409,
    UnverifiedLegsError: 422,
    ValidationFailedError: 422,
    SyncFailedError: 502,
    PrFailedError: 502,
}
DEFAULT_STATUS = 500
