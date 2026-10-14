"""AppRepoWriter against github.com: GHCR version reads and orphan-branch writes."""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from urllib.parse import quote

import httpx

from studio.logging import get_logger

__all__ = ["GithubAppWriter"]

logger = get_logger(__name__)

_API_BASE = "https://api.github.com"
_TIMEOUT_SECONDS = 10.0
_REPO_PATH = re.compile(r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$")
_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")

# auto_init's first commit lands asynchronously after the create-repo call
# returns, so the ref read that seeds a fresh repo can 404 for a few seconds.
# The poll is bounded: a repo that truly has no head still answers "" fast
# enough for the caller's rollback to run.
_HEAD_POLL_ATTEMPTS = 5
_HEAD_POLL_DELAY_SECONDS = 2.0


class GithubAppWriter:
    """Implements AppRepoWriter over the REST and git-data APIs.

    The write credential is deliberately its own token (contents read/write
    on the fleet's app repos, repo delete for the scaffold rollback, packages
    read on the org), separate from both the platform-repo PAT and the fleet
    read token: a composition without it wires no writer and onboard_app
    leaves the deploy branch to the runbook.
    The orphan branch rides the git-data API (blob-less inline trees, a
    commit with no parents, then the ref), so no clone is needed.

    The git-data API answers 409 ("Git Repository is empty") on a repository
    with no commits, so it cannot seed a virgin repo - the reason
    create_repository auto-inits and seed_branch updates that first ref
    rather than creating one. create_orphan_branch keeps its own precondition
    (a repo with history, a branch that does not exist yet), which is what
    the deploy-branch callers hold.
    """

    def __init__(self, token: str) -> None:
        self._token = token
        self._sleep: Callable[[float], None] = time.sleep
        self._last_failure = ""

    def last_failure(self) -> str:
        return self._last_failure

    def create_repository(self, *, org: str, name: str, description: str) -> bool:
        # auto_init is load-bearing, not a convenience: the git-data API refuses
        # a repository with zero commits (409, "Git Repository is empty"), so a
        # repo created empty cannot be seeded through it at all. The one throwaway
        # initial commit is what makes seed_branch's tree write legal; the seed
        # carries no base_tree, so nothing of it survives but the parent link.
        payload = self._post_json(
            f"{_API_BASE}/orgs/{org}/repos",
            {
                "name": name,
                "description": description,
                "private": True,
                "auto_init": True,
                "has_wiki": False,
                "has_projects": False,
            },
        )
        created = isinstance(payload, dict) and bool(payload.get("full_name"))
        if created:
            logger.info("Created repository %s/%s", org, name)
        return created

    def delete_repository(self, *, org: str, name: str) -> bool:
        """Delete an org repository. The rollback leg of a failed scaffold, so
        a half-built repo never outlives the act that created it. Needs
        delete_repo on the token; False when the host refuses (the caller then
        names the surviving repo rather than pretending it is gone)."""
        deleted = self._delete(f"{_API_BASE}/repos/{org}/{name}")
        if deleted:
            logger.info("Deleted repository %s/%s", org, name)
        return deleted

    def latest_semver_tag(self, *, owner: str, package: str) -> str | None:
        encoded = quote(package, safe="")
        url = (
            f"{_API_BASE}/orgs/{owner}/packages/container/{encoded}/versions?per_page=100"
        )
        payload = self._get_json(url)
        if not isinstance(payload, list):
            return None
        tags: list[tuple[int, int, int]] = []
        for version in payload:
            if not isinstance(version, dict):
                continue
            metadata = version.get("metadata") or {}
            container = metadata.get("container") if isinstance(metadata, dict) else {}
            for tag in (container or {}).get("tags") or []:
                if isinstance(tag, str) and _SEMVER.match(tag):
                    major, minor, patch = tag.split(".")
                    tags.append((int(major), int(minor), int(patch)))
        if not tags:
            logger.info("No semver tags on ghcr.io/%s/%s", owner, package)
            return None
        return ".".join(str(part) for part in max(tags))

    def create_orphan_branch(
        self, *, repo_url: str, branch: str, files: dict[str, str], message: str
    ) -> bool:
        self._last_failure = ""
        base = self._base(repo_url)
        if not base or not branch or not files:
            return False
        commit = self._commit_tree(base, files=files, message=message, parents=[])
        if not commit:
            return False
        ref = self._post_json(
            f"{base}/git/refs",
            {"ref": f"refs/heads/{branch}", "sha": commit},
        )
        created = isinstance(ref, dict) and bool(ref.get("ref"))
        if created:
            logger.info("Created orphan %s on %s (%d files)", branch, base, len(files))
        return created

    def seed_branch(
        self, *, repo_url: str, branch: str, files: dict[str, str], message: str
    ) -> bool:
        """Replace an EXISTING branch's content with exactly ``files``.

        The seeding path for a freshly created repo's default branch, where
        create_orphan_branch cannot help: that one creates a ref, and after
        auto-init the ref is already there. The commit parents the auto-init
        head (so the ref update is an ordinary fast-forward, never a force -
        a force capability on this writer would eventually overwrite a live
        deploy branch), while the tree carries no base_tree, so the branch
        ends up holding exactly ``files`` and nothing of the initial commit.
        """
        self._last_failure = ""
        base = self._base(repo_url)
        if not base or not branch or not files:
            return False
        parent = self._await_head(base, branch)
        if not parent:
            logger.info(
                "Cannot seed %s on %s: no head commit after %d reads",
                branch,
                base,
                _HEAD_POLL_ATTEMPTS,
            )
            return False
        commit = self._commit_tree(base, files=files, message=message, parents=[parent])
        if not commit:
            return False
        ref = self._patch_json(f"{base}/git/refs/heads/{branch}", {"sha": commit})
        seeded = isinstance(ref, dict) and bool(ref.get("ref"))
        if seeded:
            logger.info("Seeded %s on %s (%d files)", branch, base, len(files))
        return seeded

    def _await_head(self, base: str, branch: str) -> str:
        """The branch head's sha, polled briefly; "" when it never appears.

        Seeding races repo creation: the seed's ref read can arrive before
        auto_init's commit exists, and a single losing read here costs the
        caller the whole scaffold (the seed fails, the rollback deletes the
        repository). The poll absorbs the race without granting the writer
        any capability it did not have.
        """
        for attempt in range(_HEAD_POLL_ATTEMPTS):
            if attempt:
                self._sleep(_HEAD_POLL_DELAY_SECONDS)
            head = self._get_json(f"{base}/git/ref/heads/{branch}")
            if isinstance(head, dict):
                obj = head.get("object")
                sha = (obj or {}).get("sha", "") if isinstance(obj, dict) else ""
                if sha:
                    return str(sha)
        return ""

    def _base(self, repo_url: str) -> str:
        match = _REPO_PATH.search(repo_url)
        if not match:
            return ""
        return f"{_API_BASE}/repos/{match.group('owner')}/{match.group('repo')}"

    def _commit_tree(
        self, base: str, *, files: dict[str, str], message: str, parents: list[str]
    ) -> str:
        """Write ``files`` as a fresh tree and commit it; the commit sha, or "".

        No base_tree on purpose: the tree IS the whole content, so a seed
        cannot inherit stray files from whatever the branch held before.
        """
        tree = self._post_json(
            f"{base}/git/trees",
            {
                "tree": [
                    {"path": path, "mode": "100644", "type": "blob", "content": text}
                    for path, text in sorted(files.items())
                ]
            },
        )
        if not isinstance(tree, dict) or not tree.get("sha"):
            return ""
        commit = self._post_json(
            f"{base}/git/commits",
            {"message": message, "tree": tree["sha"], "parents": parents},
        )
        if not isinstance(commit, dict) or not commit.get("sha"):
            return ""
        return str(commit["sha"])

    def _record(self, method: str, url: str, status: int, body: str) -> None:
        """Log a refusal and keep it for the caller's message (last_failure)."""
        path = url.replace(f"{_API_BASE}/", "")
        detail = " ".join(body.split())[:200]
        self._last_failure = f"{method} {path} answered {status}: {detail}"
        logger.info("GitHub API answered %d at %s %s: %s", status, method, url, detail)

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/vnd.github+json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _get_json(self, url: str) -> object | None:
        try:
            response = httpx.get(
                url, headers=self._headers(), timeout=_TIMEOUT_SECONDS, follow_redirects=True
            )
        except httpx.HTTPError as exc:
            self._last_failure = f"{url} unreachable: {exc}"
            logger.info("GitHub API unreachable at %s: %s", url, exc)
            return None
        if response.status_code != 200:
            self._record("GET", url, response.status_code, response.text)
            return None
        self._last_failure = ""
        try:
            return response.json()
        except ValueError:
            return None

    def _post_json(self, url: str, payload: dict) -> object | None:
        return self._write_json("POST", url, payload)

    def _patch_json(self, url: str, payload: dict) -> object | None:
        return self._write_json("PATCH", url, payload)

    def _write_json(self, method: str, url: str, payload: dict) -> object | None:
        try:
            response = httpx.request(
                method, url, headers=self._headers(), json=payload, timeout=_TIMEOUT_SECONDS
            )
        except httpx.HTTPError as exc:
            self._last_failure = f"{url} unreachable: {exc}"
            logger.info("GitHub API unreachable at %s: %s", url, exc)
            return None
        if response.status_code not in (200, 201):
            # The body names the cause the status alone cannot (a 409 here is
            # "Git Repository is empty" far more often than a real conflict;
            # a 422 on the ref update is the token missing `workflow` scope,
            # since the scaffold carries .github/workflows/build.yml).
            self._record(method, url, response.status_code, response.text)
            return None
        self._last_failure = ""
        try:
            return response.json()
        except ValueError:
            return None

    def _delete(self, url: str) -> bool:
        try:
            response = httpx.delete(url, headers=self._headers(), timeout=_TIMEOUT_SECONDS)
        except httpx.HTTPError as exc:
            self._last_failure = f"{url} unreachable: {exc}"
            logger.info("GitHub API unreachable at %s: %s", url, exc)
            return False
        if response.status_code != 204:
            self._record("DELETE", url, response.status_code, response.text)
            return False
        return True
