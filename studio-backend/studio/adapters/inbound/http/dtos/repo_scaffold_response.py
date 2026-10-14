"""Response DTO for templated app-repo creation."""

from __future__ import annotations

from pydantic import BaseModel

__all__ = ["RepoScaffoldResponse"]


class RepoScaffoldResponse(BaseModel):
    """The created repository and the onboarding declaration it takes."""

    name: str
    repo_url: str
    branch: str
    deploy_branch: str
    files: tuple[str, ...]
    image_components: tuple[str, ...]
