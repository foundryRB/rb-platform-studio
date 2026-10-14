"""Raised when a git plumbing operation fails."""

from __future__ import annotations

from studio.domain.exceptions.app_error import AppError

__all__ = ["SyncFailedError"]


class SyncFailedError(AppError):
    """A git operation (clone, fetch, branch, commit, push) failed."""
