"""Root application error type."""

from __future__ import annotations

__all__ = ["AppError"]


class AppError(Exception):
    """Base class for all application errors."""
