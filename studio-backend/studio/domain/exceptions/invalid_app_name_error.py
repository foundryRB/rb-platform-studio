"""Raised when an app name is not a valid DNS label."""

from __future__ import annotations

from studio.domain.exceptions.app_error import AppError

__all__ = ["InvalidAppNameError"]


class InvalidAppNameError(AppError):
    """App names become namespaces, hostnames, and chart names: DNS labels only."""

    def __init__(self, name: str) -> None:
        super().__init__(
            f"invalid app name {name!r}: must be a lowercase DNS label "
            "(letters, digits, hyphens; starts and ends alphanumeric)"
        )
        self.name = name
