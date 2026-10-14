"""GitPr over the git CLI and the GitHub REST API, managing a clone the studio owns."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import httpx
import yaml

from studio.domain.exceptions.already_exists_error import AlreadyExistsError
from studio.domain.exceptions.direct_commit_refused_error import DirectCommitRefusedError
from studio.domain.exceptions.pr_failed_error import PrFailedError
from studio.domain.exceptions.sync_failed_error import SyncFailedError
from studio.domain.model.pr_info import PrInfo
from studio.domain.services.change_branch import CHANGE_BRANCH_PREFIXES
from studio.logging import get_logger

__all__ = ["CliGitPr"]

logger = get_logger(__name__)

_TIMEOUT_SECONDS = 120
_API_TIMEOUT_SECONDS = 30
_API_BASE = "https://api.github.com"
_REPO_PATH = re.compile(r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$")
# The lines a conflicted merge, rebase or stash pop leaves around each hunk.
_CONFLICT_MARKER = re.compile(r"^(?:<{7}|>{7})(?: |$)", flags=re.MULTILINE)


class CliGitPr:
    """Implements GitPr with subprocess git plus the GitHub pulls API.

    ensure_ready() provisions the clone on first start (token-authenticated
    remote, author identity); afterwards every operation assumes a valid work
    tree parked on the install's deploy branch. Every onboarding rides an
    onboarding branch based on the deploy branch; only the lifecycle fast path
    commits to the deploy branch directly.
    """

    def __init__(
        self,
        root: Path,
        remote_url: str,
        token: str,
        deploy_branch: str,
        author_name: str = "platform-studio",
        author_email: str = "platform-studio@localhost",
    ) -> None:
        self._root = root
        self._remote_url = remote_url
        self._token = token
        self._deploy_branch = deploy_branch
        self._author_name = author_name
        self._author_email = author_email

    def ensure_ready(self) -> None:
        """Clone on first start, pin the author identity, park on the deploy branch."""
        if not (self._root / ".git").is_dir():
            logger.info("Cloning platform repo into %s", self._root)
            self._root.parent.mkdir(parents=True, exist_ok=True)
            self._run_or_raise(
                ["clone", self._authenticated_url(), str(self._root)], cwd=self._root.parent
            )
        self._run_or_raise(["remote", "set-url", "origin", self._authenticated_url()])
        self._run_or_raise(["config", "user.name", self._author_name])
        self._run_or_raise(["config", "user.email", self._author_email])
        self._run_or_raise(["fetch", "origin"])
        self._run_or_raise(self._checkout_deploy_argv())
        logger.info("Parked on the install branch %s", self._deploy_branch)

    def commit_to_deploy(self, *, paths: tuple[str, ...], commit_message: str) -> None:
        """Commit `paths` on the deploy branch and push directly.

        The direct-commit fast path for lifecycle toggles (ADR-008). The caller
        refreshed the clone before reading and wrote its edit into the working
        tree, so the edit is committed as it stands, never stashed. When the
        upstream head moved since the refresh, the commit is rebased onto it.
        A rebase conflict, or a file carrying conflict markers or failing to
        parse as YAML (checked before the commit and again after the rebase),
        refuses the act; any failure returns the clone to the upstream head,
        so the remote either takes the toggle whole or is left untouched. A
        genuine no-op (toggling to a state already committed) is reported,
        not pushed.
        """
        deploy = self._deploy_branch
        try:
            self._run_or_raise(["checkout", deploy])
            self._run_or_raise(["add", "--", *paths])
            rc, _ = self._run(["diff", "--cached", "--quiet"])
            if rc == 0:
                logger.info("Nothing to commit for %r; already at target state", commit_message)
                return
            self._refuse_malformed(paths, commit_message)
            self._run_or_raise(["commit", "-m", commit_message])
            self._run_or_raise(["fetch", "origin"])
            rc, out = self._run(["rebase", f"origin/{deploy}"])
            if rc != 0:
                raise DirectCommitRefusedError(
                    commit_message,
                    f"{deploy} moved since it was read and the change conflicts "
                    f"with this one ({self._sanitized(out)[-500:]})",
                )
            self._refuse_malformed(paths, commit_message)
            self._run_or_raise(["push", "origin", deploy])
        except Exception:
            self._discard_direct_commit()
            raise
        logger.info("Committed %r directly to %s", commit_message, deploy)

    def _refuse_malformed(self, paths: tuple[str, ...], commit_message: str) -> None:
        """Refuse a file no commit may carry: git conflict markers anywhere, or
        YAML that does not parse."""
        for path in paths:
            file = self._root / path
            if not file.is_file():
                continue
            text = file.read_text(encoding="utf-8")
            if _CONFLICT_MARKER.search(text):
                raise DirectCommitRefusedError(commit_message, f"{path} carries conflict markers")
            if file.suffix in (".yaml", ".yml"):
                try:
                    for _ in yaml.safe_load_all(text):
                        pass
                except yaml.YAMLError as exc:
                    problem = " ".join(str(exc).split())
                    raise DirectCommitRefusedError(
                        commit_message, f"{path} does not parse as YAML ({problem})"
                    ) from exc

    def _discard_direct_commit(self) -> None:
        """Return the deploy branch to the upstream head after a direct commit
        that did not land: no rebase left in progress, no commit, no edit.
        Never raises: the failure that got here is the one the caller sees."""
        deploy = self._deploy_branch
        self._run(["rebase", "--abort"])
        rc, out = self._run(["checkout", "-f", "-B", deploy, f"origin/{deploy}"])
        if rc != 0:
            logger.warning(
                "Could not return %s to its upstream head: %s", deploy, self._sanitized(out)
            )

    def prepare_branch(self, name: str) -> None:
        """Branch from the fetched upstream deploy head; a live remote branch means
        an onboarding for this target is already pending its automated merge.

        Fetch with --prune so the existence check reads the remote's true state
        (INT-GATE-003): the studio's checkout is long-lived on a persistent
        volume, so a plain fetch leaves a stale origin/<name> ref behind after an
        abandoned onboarding's branch is deleted, wedging every re-onboard of that
        target. Pruning drops those dead refs, so only a branch still live on the
        remote trips the guard.
        """
        self._run_or_raise(["fetch", "--prune", "origin"])
        rc, _ = self._run(["rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{name}"])
        if rc == 0:
            raise AlreadyExistsError("onboarding branch", name, self._pending_detail(name))
        deploy = self._deploy_branch
        self._run_or_raise(["checkout", "-B", name, f"origin/{deploy}"])
        logger.info("Prepared branch %s from origin/%s", name, deploy)

    def finalize(
        self, *, branch: str, commit_message: str, pr_title: str, pr_body: str
    ) -> PrInfo | None:
        """Commit, push, and open the pull request as one atomic act.

        Publishing is two writes against two systems, and the second can fail
        on its own (a secondary rate limit, a transient 5xx, an unreachable
        API). A pushed branch with no pull request tracking it is invisible to
        every read the studio offers while still tripping prepare_branch's
        pending-onboarding guard, so it would wedge that target forever.
        The branch is therefore deleted again when the pull request cannot be
        opened: either the remote carries a branch with a pull request, or it
        carries nothing.
        """
        self._run_or_raise(["add", "-A"])
        rc, _ = self._run(["diff", "--cached", "--quiet"])
        if rc == 0:
            raise SyncFailedError(f"nothing to commit on {branch}")
        self._run_or_raise(["commit", "-m", commit_message])
        self._run_or_raise(["push", "-u", "origin", branch])
        deploy = self._deploy_branch
        owner, repo = self._owner_repo()
        try:
            response = self._api(
                "POST",
                f"/repos/{owner}/{repo}/pulls",
                json={"title": pr_title, "head": branch, "base": deploy, "body": pr_body},
            )
        except Exception:
            self._discard_pushed(branch)
            raise
        finally:
            self._run_or_raise(["checkout", deploy])
        pr = PrInfo(
            number=int(response["number"]),
            title=str(response["title"]),
            url=str(response["html_url"]),
            branch=branch,
            state=str(response["state"]),
            merged=bool(response.get("merged")),
        )
        logger.info("Opened %s for %s (base %s)", pr.url, branch, deploy)
        return pr

    def abort(self, branch: str) -> None:
        """Return the managed clone to a pristine deploy branch."""
        self._run(["reset", "--hard"])
        self._run(["clean", "-fd"])
        self._run_or_raise(["checkout", self._deploy_branch])
        self._run(["branch", "-D", branch])
        logger.info("Aborted branch %s", branch)

    def delete_remote_branch(self, branch: str) -> bool:
        """Delete `branch` on the remote; False when the remote does not carry it.

        Pruned-fetch first, for the reason prepare_branch prunes: the answer
        must be the remote's, not a stale ref this long-lived checkout kept.
        """
        self._run(["fetch", "--prune", "origin"])
        rc, _ = self._run(["rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}"])
        if rc != 0:
            return False
        self._run_or_raise(["push", "origin", "--delete", branch])
        self._run(["fetch", "--prune", "origin"])
        logger.info("Deleted remote branch %s", branch)
        return True

    def open_prs(self) -> tuple[PrInfo, ...]:
        """Every open pull request the studio's own gate prepared.

        Keyed on all four change-branch prefixes, not onboarding's alone: an
        offboard, a reconcile, and a settings write each ship a pull request
        the same way, and a read that showed only onboardings would leave the
        other three with no surface at all once the call that opened them
        returned. Pull requests a human opened against the platform repo stay
        out; this is the studio reporting its own work.
        """
        owner, repo = self._owner_repo()
        response = self._api_list(
            "GET", f"/repos/{owner}/{repo}/pulls", params={"state": "open"}
        )
        return tuple(
            PrInfo(
                number=int(item["number"]),
                title=str(item["title"]),
                url=str(item["html_url"]),
                branch=str(item["head"]["ref"]),
                state=str(item["state"]),
                merged=item.get("merged_at") is not None,
            )
            for item in response
            if str(item["head"]["ref"]).startswith(CHANGE_BRANCH_PREFIXES)
        )

    def get_pr(self, number: int) -> PrInfo:
        """One pull request by number: the merge-status signal a run polls.

        GET /repos/{owner}/{repo}/pulls/{number} carries the explicit merged
        boolean (true only for an actually-merged PR; a closed-not-merged PR
        stays false), so polling this distinguishes admission from
        abandonment.
        """
        owner, repo = self._owner_repo()
        response = self._api("GET", f"/repos/{owner}/{repo}/pulls/{number}")
        return PrInfo(
            number=int(response["number"]),
            title=str(response["title"]),
            url=str(response["html_url"]),
            branch=str(response["head"]["ref"]),
            state=str(response["state"]),
            merged=bool(response.get("merged")),
        )

    def prs_for_branch(self, branch: str) -> tuple[PrInfo, ...]:
        """Every pull request, of any state, whose head is `branch`."""
        owner, repo = self._owner_repo()
        response = self._api_list(
            "GET",
            f"/repos/{owner}/{repo}/pulls",
            params={"state": "all", "head": f"{owner}:{branch}"},
        )
        return tuple(
            PrInfo(
                number=int(item["number"]),
                title=str(item["title"]),
                url=str(item["html_url"]),
                branch=str(item["head"]["ref"]),
                state=str(item["state"]),
                merged=item.get("merged_at") is not None,
            )
            for item in response
        )

    def refresh(self) -> None:
        """Park on the deploy branch at its upstream head.

        Between acts the deploy branch carries nothing of the studio's own: a
        direct commit either lands on the remote or is discarded, and every
        other change rides its own branch. So the upstream head is the state,
        and the clone takes it outright, as a restarted pod does, rather than
        replaying leftovers onto it, where a rebase or a stash pop could
        conflict. Every direct-commit act refreshes before it reads.
        """
        deploy = self._deploy_branch
        self._run(["rebase", "--abort"])
        self._run_or_raise(["fetch", "origin"])
        self._run_or_raise(["checkout", "-f", "-B", deploy, f"origin/{deploy}"])

    def _discard_pushed(self, branch: str) -> None:
        """Undo finalize's push. Never raises: the publishing failure is the
        one the caller must see, and a cleanup that fails on top of it would
        replace the diagnosis with its own."""
        try:
            self.delete_remote_branch(branch)
        except Exception:  # noqa: BLE001 - the original failure outranks this one
            logger.warning(
                "Could not delete %s after the pull request failed to open; it is "
                "orphaned on the remote and cancel_onboarding clears it",
                branch,
                exc_info=True,
            )

    def _pending_detail(self, branch: str) -> str:
        """Why a live remote branch blocks, in the operator's two cases.

        A pull request open against it means the change is in flight and the
        answer is to wait; none referencing it means the branch outlived (or
        never had) its pull request and the answer is to cancel it. The
        refusal carries which, because the responses are opposite.
        """
        try:
            prs = self.prs_for_branch(branch)
        except PrFailedError as exc:
            return f"its pull requests could not be read: {exc}"
        pending = next((pr for pr in prs if pr.state == "open"), None)
        if pending is not None:
            return f"pull request {pending.url} is open against it, awaiting its automated merge"
        if prs:
            latest = prs[0]
            settled = "merged" if latest.merged else "closed unmerged"
            return (
                f"its pull request {latest.url} is {settled} and the branch outlived it; "
                f"cancel_onboarding {branch} clears it"
            )
        return (
            "no pull request references it, so it is an orphan of a publish that pushed but "
            f"could not open one; cancel_onboarding {branch} clears it"
        )

    def _checkout_deploy_argv(self) -> list[str]:
        """Park on the deploy branch, creating the local branch from origin's.

        `-B` resets a pre-existing local branch onto the fetched upstream head,
        so a restarted pod converges on the remote's state rather than a stale
        local one.
        """
        return ["checkout", "-B", self._deploy_branch, f"origin/{self._deploy_branch}"]

    def _authenticated_url(self) -> str:
        if self._remote_url.startswith("https://") and "@" not in self._remote_url:
            return self._remote_url.replace(
                "https://", f"https://x-access-token:{self._token}@", 1
            )
        return self._remote_url

    def _owner_repo(self) -> tuple[str, str]:
        match = _REPO_PATH.search(self._remote_url)
        if not match:
            raise PrFailedError(f"cannot derive owner/repo from remote URL: {self._remote_url}")
        return match.group("owner"), match.group("repo")

    def _api(self, method: str, path: str, **kwargs: object):
        response = self._send(method, f"{_API_BASE}{path}", **kwargs)
        if response.status_code in (307, 308) and method.upper() != "GET":
            # 307 and 308 preserve the method AND the body by definition, which
            # is exactly why GitHub answers a transferred repository's write with
            # one. Following it is safe where following a 301, 302 or 303 is not:
            # httpx demotes those to GET, so a followed write would fetch a
            # collection instead of creating anything and hand back a plausible
            # answer, leaving a pushed branch that no pull request tracks - the
            # state INT-GATE-004 exists to prevent. Those still fail below.
            #
            # Followed once, and only back to the API's own origin: the request
            # carries a Bearer token, and a redirect pointing anywhere else must
            # never be handed that credential.
            location = response.headers.get("location", "")
            if location.startswith(f"{_API_BASE}/"):
                response = self._send(method, location, **kwargs)
        if response.status_code >= 300:
            # 3xx counted as success until a transferred repository answered 301
            # with a JSON OBJECT, which open_prs iterated as if it were the
            # pull-request array: its keys are strings, so the first field access
            # died as "string indices must be integers, not 'str'" and every
            # app_status call reported onboarding_pr skipped with that text,
            # naming neither the repository nor the redirect. A 3xx is not a
            # result.
            location = response.headers.get("location", "")
            raise PrFailedError(
                f"GitHub API {method} {path} answered {response.status_code}: "
                + (f"redirected to {location}: " if location else "")
                + response.text[:500]
            )
        return response.json()

    def _send(self, method: str, url: str, **kwargs: object) -> httpx.Response:
        """One request, with the API headers and the read/write redirect rule.

        A READ follows any redirect: that is what GitHub's own 301 body advises,
        and it keeps every read working across a repository rename or transfer.
        A WRITE never does here, because httpx would demote it to GET; the
        method-preserving 307 and 308 are followed explicitly by _api instead.
        """
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        try:
            return httpx.request(
                method,
                url,
                headers=headers,
                timeout=_API_TIMEOUT_SECONDS,
                follow_redirects=method.upper() == "GET",
                **kwargs,  # type: ignore[arg-type]
            )
        except httpx.HTTPError as exc:
            raise PrFailedError(f"GitHub API unreachable: {exc}") from exc

    def _api_list(self, method: str, path: str, **kwargs: object) -> list:
        """A collection endpoint's response, refusing anything that is not one.

        _api refuses the redirect that produced the object body once; this is the
        backstop for whatever else ever answers off-shape, so the failure carries
        the endpoint and the body rather than a TypeError from the first field
        access two frames away.
        """
        response = self._api(method, path, **kwargs)
        if not isinstance(response, list):
            raise PrFailedError(
                f"GitHub API {method} {path} answered "
                f"{type(response).__name__}, not a list: {str(response)[:500]}"
            )
        return response

    def _run(self, argv: list[str], cwd: Path | None = None) -> tuple[int, str]:
        try:
            proc = subprocess.run(
                ["git", *argv],
                cwd=cwd or self._root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return 1, str(exc)
        return proc.returncode, proc.stdout + proc.stderr

    def _run_or_raise(self, argv: list[str], cwd: Path | None = None) -> str:
        rc, out = self._run(argv, cwd=cwd)
        if rc != 0:
            raise SyncFailedError(f"git {argv[0]}: {self._sanitized(out)[-2000:]}")
        return out

    def _sanitized(self, out: str) -> str:
        return (out.replace(self._token, "***") if self._token else out).strip()
