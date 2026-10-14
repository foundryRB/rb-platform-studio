"""Raised when an app's repository name is not a valid repo name."""

from __future__ import annotations

from studio.domain.exceptions.app_error import AppError

__all__ = ["InvalidRepoNameError"]


class InvalidRepoNameError(AppError):
    """Repo names are a host label, not a DNS label: the org's own alphabet.

    The app name is a DNS label because it becomes a namespace and a hostname.
    A repository name becomes neither; it is the last segment of the URL the
    Application points at, so it takes what the repo host allows (letters in
    either case, digits, dot, hyphen, underscore).
    """

    def __init__(self, repo: str) -> None:
        super().__init__(
            f"invalid repo name {repo!r}: must be a repository name under the org "
            "(letters, digits, dot, hyphen, underscore; starts alphanumeric), "
            "not a URL or an owner/repo pair"
        )
        self.repo = repo
