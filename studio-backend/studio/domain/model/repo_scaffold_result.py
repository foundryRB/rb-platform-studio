"""The outcome of creating a templated app repository."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["RepoScaffoldResult"]


@dataclass(frozen=True)
class RepoScaffoldResult:
    """A created walking-skeleton repository and what onboarding it takes.

    ``image_components`` is the declaration the scaffold was rendered for
    (``["app", "docs"]``): the onboarding that follows passes it verbatim, so
    the aliases and the released set agree from birth. ``deploy_branch`` is
    the install's ``deploy-<install>`` branch when this creation stood it up
    (pinned at the 1.0.0 the first conventional push releases), empty when it
    did not.
    """

    name: str
    repo_url: str
    branch: str
    deploy_branch: str
    files: tuple[str, ...]
    image_components: tuple[str, ...]
