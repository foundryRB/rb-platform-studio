"""One curated platform-level knob, read from the install's deploy branch."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["PlatformSetting"]


@dataclass(frozen=True)
class PlatformSetting:
    """A named platform value the operator tunes through the studio.

    Platform-level knobs (retention horizons, and similar) live in the install's
    values on its deploy branch, not in a tool's own Settings surface. A
    PlatformSetting names one such knob, where its value is read from and
    written to, and what it currently resolves to.

    `value` and `default` are distinct facts, and collapsing them would lie. A
    `value` of None means the install's values.yaml sets nothing here, so the
    chart's `default` is in force; a `value` equal to `default` means the
    install has pinned that number explicitly, which survives a chart whose
    default later moves. What the component actually runs with is `effective`.
    """

    key: str
    label: str
    category: str
    unit: str
    value: str | None
    default: str
    source: str
    field: str
    description: str

    @property
    def effective(self) -> str:
        """The horizon in force: the install's own value, else the chart's default."""
        return self.value if self.value is not None else self.default
