"""The curated registry of platform knobs the studio surfaces, and how each
one's value is read from and written to the install's deploy branch.

Deliberately a fixed, named registry rather than a generic values editor: a
platform setting is a knob an operator actually tunes (a retention horizon, a
resource budget), described here by exactly where it lives in the install's
values. Anything not in this registry stays "edit the repo like an engineer" -
the boundary issue #6 left open, drawn here at the registry's edge.

Every knob addresses `values.yaml` ON THE DEPLOY BRANCH, which is the install's
own Helm values file for the platform chart (root/platform.yaml passes it as
`$branch/values.yaml`, ADR-032). That is the only place a studio setting can
live: the deploy branch is the whole of the studio's checkout - it carries
foundry.yaml, values.yaml, root/ and teams/, and no `k8s/` chart source at all.
A knob pointed at a chart template would read null forever and write a file the
branch does not have.

The reciprocal half is in the platform chart: each field named here reads from
its own `.Values.*` key rather than a literal (foundry-platform's
INT-FOUNDRY-062 holds that for the observability horizons, INT-FOUNDRY-068 for
the event bus, both in both directions). Without it a write here would land in
values.yaml, merge, reconcile, and change nothing.

Reads parse values.yaml as YAML - it is an ordinary values file, not a Helm
template. Writes are textual and surgical, so every comment and every unrelated
key survives byte-identical (the PlatformRepository contract, and what makes a
rolled-back gate leave the checkout untouched).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

import yaml

from studio.domain.model.platform_setting import PlatformSetting

__all__ = [
    "CuratedSetting",
    "CURATED_SETTINGS",
    "VALUES_FILE",
    "build_setting",
    "find_setting",
    "resolve_value",
    "set_value",
    "validation_error",
]

# The install's own values file on the deploy branch: every curated knob lives
# here, because it is the only file the platform chart reads per-install values
# from and the only one the studio's checkout carries.
VALUES_FILE = "values.yaml"

_INDENT = "  "


@dataclass(frozen=True)
class CuratedSetting:
    """A knob's fixed facts, minus its current value: what it is, where in the
    install's values it lives, and what the chart falls back to when unset."""

    key: str
    label: str
    category: str
    unit: str
    path: tuple[str, ...]
    default: str
    description: str

    @property
    def field(self) -> str:
        """The dotted values path, as an operator would grep for it."""
        return ".".join(self.path)


# The observability retention horizons: the knobs issue #6 named ("retention
# horizons"), at the exact Loki value it raised, plus its two siblings, which
# are the same knob for the other two signals. Then the event bus's own horizon,
# the same shape one capability over: a signal kept for a bounded window by a
# component the operator sizes. The registry grows a knob at a time, each
# pointing at where its value lives in the install's values and at the chart
# default that holds when the install sets nothing.
CURATED_SETTINGS: tuple[CuratedSetting, ...] = (
    CuratedSetting(
        key="observability.log-retention",
        label="Log retention",
        category="observability",
        unit="duration",
        path=("observability", "logRetention"),
        default="720h",
        description=(
            "How long Loki keeps ingested logs before the compactor drops them. "
            "The concrete knob issue #6 raised: it last moved (7d to 30d) by a "
            "hand-edit to the platform chart and a pin bump, which is the "
            "engineer edit this surface exists to replace."
        ),
    ),
    CuratedSetting(
        key="observability.metrics-retention",
        label="Metrics retention",
        category="observability",
        unit="duration",
        path=("observability", "metricsRetention"),
        default="10d",
        description=(
            "How long Prometheus keeps scraped metrics before dropping them "
            "(its prometheusSpec.retention)."
        ),
    ),
    CuratedSetting(
        key="observability.traces-retention",
        label="Trace retention",
        category="observability",
        unit="duration",
        path=("observability", "tracesRetention"),
        default="72h",
        description=(
            "How long Tempo keeps ingested traces before compaction drops them. "
            "Traefik emits one edge span per proxied request, so this horizon "
            "sizes the front-door request history."
        ),
    ),
    CuratedSetting(
        key="messaging.retention",
        label="Event retention",
        category="messaging",
        unit="duration",
        path=("messaging", "retention"),
        default="168h",
        description=(
            "How long the shared event bus keeps published events before the "
            "FOUNDRY_EVENTS stream drops them at its max_age. This is a replay "
            "window for durable consumers, not an archive: the bus is not the "
            "record of what happened, so raising it past a horizon a consumer "
            "could plausibly be offline for buys nothing."
        ),
    ),
    CuratedSetting(
        key="arc.max-runners",
        label="Maximum CI runners",
        category="delivery",
        unit="count",
        path=("arc", "maxRunners"),
        default="8",
        description=(
            "Maximum concurrent ARC runner pods. Set to 0 with minRunners at 0 "
            "to drain the jobs queue. Choose a limit that fits this install's capacity."
        ),
    ),
)

# A Go/Prometheus duration: a positive count and one unit. Loki reads 720h,
# Prometheus 10d, Tempo 72h; all three accept this shape. A bare number is
# refused on purpose - unitless, it means different things to each component.
_DURATION = re.compile(r"^[1-9]\d*(ms|s|m|h|d|w|y)$")
_COUNT = re.compile(r"^(0|[1-9][0-9]*)$")

_VALIDATORS: dict[str, Callable[[str], str | None]] = {
    "duration": lambda value: (
        None
        if _DURATION.match(value)
        else (
            f"{value!r} is not a duration: expected a positive count and a unit "
            "(ms, s, m, h, d, w, y), for example '720h', '30d'"
        )
    ),
    "count": lambda value: (
        None if _COUNT.fullmatch(value) else f"{value!r} is not a non-negative integer"
    ),
}


def find_setting(key: str) -> CuratedSetting | None:
    """The curated knob with this key, or None when the registry has no such knob."""
    return next((setting for setting in CURATED_SETTINGS if setting.key == key), None)


def validation_error(curated: CuratedSetting, value: str) -> str | None:
    """Why `value` is not admissible for this knob, or None when it is.

    A knob with no validator for its unit accepts any non-empty value: the gate
    downstream still judges the whole candidate state, so an unvalidated unit
    fails loudly at conformance rather than silently here.
    """
    if not value.strip():
        return "a setting value cannot be empty"
    validator = _VALIDATORS.get(curated.unit)
    return validator(value) if validator else None


def resolve_value(text: str | None, path: tuple[str, ...]) -> str | None:
    """The scalar at `path` in a values file, or None when the install sets none.

    None is a real answer, not an error: it means the deploy branch overrides
    nothing here and the chart's own default is in force. A path that resolves
    to a mapping or a list resolves to None too - the studio has no single
    scalar to render or replace.
    """
    if not text:
        return None
    try:
        node: object = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    if node is None or isinstance(node, (dict, list)):
        return None
    if isinstance(node, bool):
        return "true" if node else "false"
    return str(node)


def build_setting(curated: CuratedSetting, values_text: str | None) -> PlatformSetting:
    """Join a curated knob with the value the install's values file sets for it."""
    return PlatformSetting(
        key=curated.key,
        label=curated.label,
        category=curated.category,
        unit=curated.unit,
        value=resolve_value(values_text, curated.path),
        default=curated.default,
        source=VALUES_FILE,
        field=curated.field,
        description=curated.description,
    )


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip())


def _is_blank(line: str) -> bool:
    return not line.strip()


def _block_end(lines: list[str], start: int, parent_indent: int) -> int:
    """Index one past the last line belonging to the block opened above `start`.

    Trailing blank lines fall outside the block, so an insertion lands against
    the block's last real entry rather than after the gap that separates it from
    whatever follows.
    """
    end = start
    for index in range(start, len(lines)):
        line = lines[index]
        if _is_blank(line):
            continue
        if _indent_of(line) <= parent_indent:
            break
        end = index + 1
    return end


def _find_key(lines: list[str], start: int, end: int, key: str, indent: int) -> int | None:
    """Index of `key:` declared at exactly `indent` within [start, end), or None."""
    pattern = re.compile(rf"^{' ' * indent}{re.escape(key)}\s*:")
    for index in range(start, min(end, len(lines))):
        line = lines[index]
        if _is_blank(line) or line.lstrip().startswith("#"):
            continue
        if pattern.match(line):
            return index
    return None


def set_value(text: str, path: tuple[str, ...], value: str) -> str:
    """`text` with the scalar at `path` set to `value`, everything else intact.

    Surgical by design: the deploy branch's values.yaml is a hand-authored file
    carrying an install's comments and layout, and a round-trip through a YAML
    dumper would reformat all of it into an unreviewable diff. Three cases:

    - the key exists: its line is rewritten in place;
    - the key is absent but its parent block exists: it is appended to that
      block, at the block's own indentation;
    - the parent block is absent: the whole chain is appended to the file.

    Any inline comment on a rewritten key's line is dropped, deliberately. A
    comment sits next to a value to explain THAT value ("# 30 days: match the
    failed-run horizon"), and the studio cannot rewrite it to stay true; a
    silently false comment on a config value is worse than an absent one, and
    the change is a reviewed pull request, so nothing disappears unseen.
    """
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(newline)
    # A trailing newline leaves an empty final element; hold it back so
    # appends land before it and the file keeps exactly one.
    trailer: list[str] = []
    while lines and _is_blank(lines[-1]):
        trailer.insert(0, lines.pop())

    start, end, indent = 0, len(lines), 0
    for depth, key in enumerate(path):
        index = _find_key(lines, start, end, key, indent)
        is_leaf = depth == len(path) - 1
        if index is None:
            # This level is missing: append it, and every level below it, to
            # whatever block we reached.
            block = [
                f"{' ' * (indent + len(_INDENT) * offset)}{name}:"
                + (f" {value}" if offset == len(path) - depth - 1 else "")
                for offset, name in enumerate(path[depth:])
            ]
            lines[end:end] = block
            return newline.join(lines + trailer)
        if is_leaf:
            lines[index] = f"{' ' * indent}{key}: {value}"
            return newline.join(lines + trailer)
        start = index + 1
        end = _block_end(lines, start, indent)
        # Adopt the block's own indentation so a file written with 4 spaces (or
        # any other width) keeps it; fall back to the default for an empty block.
        child = next(
            (lines[i] for i in range(start, end) if not _is_blank(lines[i])),
            None,
        )
        indent = _indent_of(child) if child is not None else indent + len(_INDENT)
    return newline.join(lines + trailer)
