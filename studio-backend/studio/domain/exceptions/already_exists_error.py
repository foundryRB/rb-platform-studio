"""Raised when creating something that already exists."""

from __future__ import annotations

from studio.domain.exceptions.app_error import AppError

__all__ = ["AlreadyExistsError"]


class AlreadyExistsError(AppError):
    """The target (manifest entry, team folder, branch) already exists.

    ``detail`` carries what the caller does about it when the bare fact does
    not say: a live onboarding branch means either a change in flight (wait
    for its merge) or one orphaned on the remote (cancel it), and those call
    for opposite responses.
    """

    def __init__(self, kind: str, identifier: str, detail: str | None = None) -> None:
        message = f"{kind} already exists: {identifier}"
        super().__init__(f"{message} - {detail}" if detail else message)
        self.kind = kind
        self.identifier = identifier
        self.detail = detail
