"""Raised when a manifest role is neither of the two the manifest declares."""

from __future__ import annotations

from studio.domain.exceptions.app_error import AppError

__all__ = ["InvalidRoleError"]


class InvalidRoleError(AppError):
    """The install manifest lists apps under exactly two roles (ADR-032)."""

    def __init__(self, role: str) -> None:
        super().__init__(f"invalid manifest role {role!r}: must be 'parts' or 'output'")
        self.role = role
