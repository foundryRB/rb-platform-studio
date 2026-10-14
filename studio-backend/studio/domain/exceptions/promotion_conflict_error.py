"""Raised when an alias already carries a tag filter the freeze cannot own."""

from __future__ import annotations

from studio.domain.exceptions.app_error import AppError

__all__ = ["PromotionConflictError"]


class PromotionConflictError(AppError):
    """The alias's ignore-tags annotation is an operator's filter, not the freeze.

    Freezing writes ``<alias>.ignore-tags: "*"``. An alias already carrying an
    ignore-tags with any other value has a real filter someone authored;
    overwriting it would silently widen or narrow what that alias promotes, and
    adding a second one would be a duplicate mapping key YAML last-key-wins
    would drop. The toggle refuses instead of doing either.
    """

    def __init__(self, name: str, alias: str, existing: str) -> None:
        super().__init__(
            f"cannot freeze promotion for {name}: its {alias!r} alias already carries "
            f"ignore-tags: {existing} , a filter the freeze would have to overwrite "
            "(resolve it before freezing)"
        )
        self.name = name
        self.alias = alias
        self.existing = existing
