"""Raised when an image-component name cannot become an image binding."""

from __future__ import annotations

from studio.domain.exceptions.app_error import AppError

__all__ = ["InvalidImageComponentError"]


class InvalidImageComponentError(AppError):
    """Component names become GHCR package suffixes (<app>-<comp>) and helm
    values keys (<app>.images.<comp>): lowercase labels only, no duplicates."""

    def __init__(self, components: tuple[str, ...]) -> None:
        listed = ", ".join(repr(c) for c in components)
        super().__init__(
            f"invalid image component(s) {listed}: each must be a unique lowercase "
            "label (letters, digits, hyphens; starts and ends alphanumeric), and a "
            "lone 'app' is the single-image shape - declare no components instead"
        )
        self.components = components
