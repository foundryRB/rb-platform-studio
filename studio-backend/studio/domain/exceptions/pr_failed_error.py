"""Raised when the pull-request API call fails."""

from __future__ import annotations

from studio.domain.exceptions.app_error import AppError

__all__ = ["PrFailedError"]


class PrFailedError(AppError):
    """The branch was pushed but the pull request could not be opened or listed."""
