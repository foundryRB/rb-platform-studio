"""Raised when an app's Application declares no Image Updater bindings."""

from __future__ import annotations

from studio.domain.exceptions.app_error import AppError

__all__ = ["PromotionUnboundError"]


class PromotionUnboundError(AppError):
    """There is no promotion to freeze: no image-list, so nothing is watched.

    Image Updater selects its working set on the image-list annotation, so an
    Application without one already promotes nothing. Reporting that is more
    use than silently succeeding on a toggle that changed nothing.
    """

    def __init__(self, name: str) -> None:
        super().__init__(
            f"cannot freeze promotion for {name}: its Application declares no Image "
            "Updater image-list, so no image is watched and nothing promotes already"
        )
        self.name = name
