"""AppRepoSource over raw.githubusercontent.com and the GitHub REST API."""

from __future__ import annotations

import re
from urllib.parse import urlencode

import httpx
import yaml

from studio.domain.model.commit_info import CommitInfo
from studio.domain.model.workflow_run import WorkflowRun
from studio.logging import get_logger

__all__ = ["GithubAppRepo"]

logger = get_logger(__name__)

_RAW_BASE = "https://raw.githubusercontent.com"
_API_BASE = "https://api.github.com"
_TIMEOUT_SECONDS = 10
_REPO_PATH = re.compile(r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$")


class GithubAppRepo:
    """Implements AppRepoSource against github.com.

    File reads try anonymous raw.githubusercontent.com first: it serves any
    public repo free of the API's anonymous rate limit. With a token
    configured, a second attempt rides the contents API, which honors
    fine-grained PATs on the private repos they cover; the fleet's app repos
    are private, so arming the app-repo conformance rows means granting the
    studio's token contents read on them. Repo and branch facts (the default
    branch, a branch's file listing) have no raw-host equivalent and ride the
    REST API directly. Every failure - unknown repo, missing branch or file,
    unreachable host, non-mapping YAML - answers None: each leg is team-owned
    and legitimately absent until the team stands it up, so the caller
    reports the dependent row skipped rather than guessed.
    """

    def __init__(self, token: str = "") -> None:
        self._token = token

    def deploy_values(self, *, repo_url: str, branch: str, path: str) -> dict | None:
        text = self.file_text(repo_url=repo_url, branch=branch, path=path)
        if text is None:
            return None
        try:
            parsed = yaml.safe_load(text)
        except yaml.YAMLError:
            logger.info("Deploy values at %s@%s:%s are not valid YAML", repo_url, branch, path)
            return None
        return parsed if isinstance(parsed, dict) else None

    def branch_head(self, *, repo_url: str, branch: str) -> str | None:
        if not branch:
            return None
        payload = self._api_json(f"repos/{{owner}}/{{repo}}/commits/{branch}", repo_url=repo_url)
        if not isinstance(payload, dict):
            return None
        return str(payload.get("sha") or "") or None

    def file_text(self, *, repo_url: str, branch: str, path: str) -> str | None:
        match = _REPO_PATH.search(repo_url)
        if not match or not branch:
            return None
        owner, repo = match.group("owner"), match.group("repo")
        attempts: list[tuple[str, dict[str, str]]] = [
            (f"{_RAW_BASE}/{owner}/{repo}/{branch}/{path}", {})
        ]
        if self._token:
            attempts.append(
                (
                    f"{_API_BASE}/repos/{owner}/{repo}/contents/{path}?ref={branch}",
                    {
                        "Authorization": f"Bearer {self._token}",
                        "Accept": "application/vnd.github.raw+json",
                    },
                )
            )
        status = 0
        for url, headers in attempts:
            try:
                response = httpx.get(
                    url, headers=headers, timeout=_TIMEOUT_SECONDS, follow_redirects=True
                )
            except httpx.HTTPError as exc:
                logger.info("App-repo file unreachable at %s: %s", url, exc)
                continue
            status = response.status_code
            if status != 200:
                continue
            return response.text
        logger.info(
            "App-repo file not readable at %s/%s@%s:%s (%d)", owner, repo, branch, path, status
        )
        return None

    def repo_exists(self, *, repo_url: str) -> bool | None:
        """Whether github.com serves the repo to this caller.

        200 is visible; 404 is the host's definite "not there for you" (no
        such repo under that owner, or private and outside the token's grant -
        GitHub answers 404 for both rather than leak existence, and either way
        no app-side leg can be read). Every other answer (unreachable,
        credentials rejected, rate limit) proves nothing and reports None.
        """
        match = _REPO_PATH.search(repo_url)
        if not match:
            return None
        owner, repo = match.group("owner"), match.group("repo")
        url = f"{_API_BASE}/repos/{owner}/{repo}"
        headers = {"Accept": "application/vnd.github+json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        try:
            response = httpx.get(
                url, headers=headers, timeout=_TIMEOUT_SECONDS, follow_redirects=True
            )
        except httpx.HTTPError as exc:
            logger.info("App-repo API unreachable at %s: %s", url, exc)
            return None
        if response.status_code == 200:
            return True
        if response.status_code == 404:
            logger.info("App repo %s/%s is not visible to the studio", owner, repo)
            return False
        logger.info("App-repo API answered %d at %s", response.status_code, url)
        return None

    def default_branch(self, *, repo_url: str) -> str | None:
        payload = self._api_json("repos/{owner}/{repo}", repo_url=repo_url)
        if not isinstance(payload, dict):
            return None
        branch = payload.get("default_branch")
        return branch if isinstance(branch, str) and branch else None

    def branch_paths(self, *, repo_url: str, branch: str) -> frozenset[str] | None:
        if not branch:
            return None
        payload = self._api_json(
            f"repos/{{owner}}/{{repo}}/git/trees/{branch}?recursive=1", repo_url=repo_url
        )
        if not isinstance(payload, dict):
            return None
        if payload.get("truncated"):
            # A listing the API could not complete proves nothing about what
            # the branch lacks; answer unreadable rather than half a tree.
            logger.info("Branch listing truncated for %s@%s", repo_url, branch)
            return None
        return frozenset(
            str(item.get("path"))
            for item in payload.get("tree") or []
            if isinstance(item, dict) and item.get("type") == "blob"
        )

    def latest_workflow_run(self, *, repo_url: str, branch: str) -> WorkflowRun | None:
        """The latest completed run on ``branch``, off the actions API.

        GET /repos/{owner}/{repo}/actions/runs?branch=<branch>&status=completed
        &per_page=1 answers newest-first, so the first entry is the freshest
        completed verdict; its conclusion is the CI leg of the evidence chain.
        """
        if not branch:
            return None
        query = urlencode({"branch": branch, "status": "completed", "per_page": 1})
        payload = self._api_json(
            f"repos/{{owner}}/{{repo}}/actions/runs?{query}", repo_url=repo_url
        )
        if not isinstance(payload, dict):
            return None
        runs = payload.get("workflow_runs")
        if not isinstance(runs, list) or not runs or not isinstance(runs[0], dict):
            return None
        run = runs[0]
        return WorkflowRun(
            name=str(run.get("name") or run.get("display_title") or ""),
            conclusion=str(run.get("conclusion") or ""),
            url=str(run.get("html_url") or ""),
            completed_at=str(run.get("updated_at") or ""),
        )

    def latest_commit(self, *, repo_url: str, branch: str, path: str) -> CommitInfo | None:
        """The latest commit on ``branch`` touching ``path``, off the commits API."""
        if not branch or not path:
            return None
        query = urlencode({"sha": branch, "path": path, "per_page": 1})
        payload = self._api_json(f"repos/{{owner}}/{{repo}}/commits?{query}", repo_url=repo_url)
        if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
            return None
        item = payload[0]
        commit = item.get("commit") if isinstance(item.get("commit"), dict) else {}
        committer = commit.get("committer") if isinstance(commit.get("committer"), dict) else {}
        message = str(commit.get("message") or "").splitlines()
        return CommitInfo(
            sha=str(item.get("sha") or ""),
            message=message[0] if message else "",
            committed_at=str(committer.get("date") or ""),
        )

    def _api_json(self, path_template: str, *, repo_url: str) -> object | None:
        match = _REPO_PATH.search(repo_url)
        if not match:
            return None
        owner, repo = match.group("owner"), match.group("repo")
        url = f"{_API_BASE}/{path_template.format(owner=owner, repo=repo)}"
        headers = {"Accept": "application/vnd.github+json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        try:
            response = httpx.get(
                url, headers=headers, timeout=_TIMEOUT_SECONDS, follow_redirects=True
            )
        except httpx.HTTPError as exc:
            logger.info("App-repo API unreachable at %s: %s", url, exc)
            return None
        if response.status_code != 200:
            logger.info("App-repo API answered %d at %s", response.status_code, url)
            return None
        try:
            return response.json()
        except ValueError:
            logger.info("App-repo API answered non-JSON at %s", url)
            return None
