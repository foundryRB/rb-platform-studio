"""Raised when the studio is asked to pause the app it runs as."""

from __future__ import annotations

from studio.domain.exceptions.app_error import AppError

__all__ = ["SelfPauseError"]


class SelfPauseError(AppError):
    """Pausing the studio's own app would scale away the control plane that resumes it."""

    def __init__(self, name: str) -> None:
        super().__init__(
            f"cannot pause {name}: it is the studio's own control plane, so pausing it "
            "would leave nothing to resume it from (resume it from git if you must)"
        )
        self.name = name
