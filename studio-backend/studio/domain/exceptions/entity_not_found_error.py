"""Raised when a requested entity does not exist."""

from __future__ import annotations

from studio.domain.exceptions.app_error import AppError

__all__ = ["EntityNotFoundError"]


class EntityNotFoundError(AppError):
    """A named entity (app, manifest, claim) was not found."""

    def __init__(self, kind: str, identifier: str) -> None:
        super().__init__(f"{kind} not found: {identifier}")
        self.kind = kind
        self.identifier = identifier
