"""Raised when an offboarding names the studio itself."""

from __future__ import annotations

from studio.domain.exceptions.app_error import AppError

__all__ = ["SelfOffboardError"]


class SelfOffboardError(AppError):
    """The studio must not remove its own manifest entry and team folder.

    Offboarding the studio prunes its Application, namespace, and Gateway on
    the next sync: the surface performing the removal disappears mid-flight,
    and with it the only supported path to undo the act. Retiring the studio
    is a platform-maintainer act against the deploy branch directly, not a
    call on the studio's own API.
    """

    def __init__(self, name: str) -> None:
        super().__init__(
            f"refusing to offboard {name!r}: that is this studio itself. "
            "Retiring the studio is a platform-maintainer act on the deploy "
            "branch, not a call on the studio's own API."
        )
