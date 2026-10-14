"""The install's registry fact (the platform's ADR-044, its #164).

Where THIS install's own images and charts live, read off the deploy branch's
values.yaml `registry` block the way the default brokers are (ADR-045): an
install fact the studio renders with, never a constant of the studio's own.
A branch that predates the block (a chart below 2.2.0 carries ghcr.io itself)
is `declared == False`, and callers fall back to GHCR under the app-repo org,
which is exactly what such a branch's chart does.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InstallRegistry:
    """host/owner prefix every image and chart reference starts with, plus the
    optional pull-secret name. An empty pull_secret on a declared registry is
    deliberate (a Ground whose pulls ride node identity), not a missing value."""

    host: str = ""
    owner: str = ""
    pull_secret: str = ""

    @property
    def declared(self) -> bool:
        return bool(self.host and self.owner)

    @property
    def prefix(self) -> str:
        """`<host>/<owner>`, or empty when undeclared."""
        return f"{self.host}/{self.owner}" if self.declared else ""

    def prefix_or_ghcr(self, org: str) -> str:
        """The declared prefix, or GHCR under ``org`` for a pre-block branch."""
        return self.prefix or f"ghcr.io/{org.lower()}"

    def pull_secret_or_ghcr(self) -> str:
        """The declared pull-secret name (its emptiness kept: declared-and-empty
        is the node-identity shape), or ghcr-pull for a pre-block branch."""
        return self.pull_secret if self.declared else "ghcr-pull"
