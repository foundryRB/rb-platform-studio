"""Raised when a lifecycle toggle's direct commit cannot land as written."""

from __future__ import annotations

from studio.domain.exceptions.app_error import AppError

__all__ = ["DirectCommitRefusedError"]


class DirectCommitRefusedError(AppError):
    """The direct commit was refused before it reached the deploy branch.

    Either the deploy branch moved after the toggle read it and rebasing the
    toggle's commit onto it conflicts, or a file the commit would carry holds
    git conflict markers or does not parse as YAML. The remote is untouched
    and the studio's clone is back on the remote head; the toggle can be
    retried once the branch settles, or the file repaired first.
    """

    def __init__(self, commit_message: str, reason: str) -> None:
        super().__init__(
            f"refused {commit_message!r}: {reason}; the deploy branch is untouched"
        )
        self.commit_message = commit_message
        self.reason = reason
