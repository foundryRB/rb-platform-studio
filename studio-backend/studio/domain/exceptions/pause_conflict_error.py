"""Raised when an app's Application already carries a foreign source.helm block."""

from __future__ import annotations

from studio.domain.exceptions.app_error import AppError

__all__ = ["PauseConflictError"]


class PauseConflictError(AppError):
    """The Application's spec.source.helm is reserved for the pause override (ADR-030).

    A pre-existing helm block means the scale-to-zero override cannot be added
    without producing a duplicate mapping key that would silently drop it, so
    pause refuses instead of corrupting the manifest.
    """

    def __init__(self, name: str) -> None:
        super().__init__(
            f"cannot pause {name}: its Application already carries a spec.source.helm block, "
            "which the scale-to-zero override reserves (resolve it before pausing)"
        )
        self.name = name
