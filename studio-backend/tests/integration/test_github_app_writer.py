"""GithubAppWriter tests for the two branch writes (the REST API faked).

These pin the one distinction the adapter exists to keep. GitHub's git-data
API refuses a repository with no commits (409, "Git Repository is empty"), so
the writer has two branch legs with opposite preconditions, and getting them
backwards is invisible to every fake that just answers True:

* create_orphan_branch CREATES a ref, parentless, on a repo that has history
  (the deploy-branch callers).
* seed_branch UPDATES a ref that already exists, parented on its head (a
  freshly created repo's auto-init default branch).

The auto_init assertion is the regression guard proper: it is the flag whose
absence let a scaffolded repo ship carrying nothing but its delivery scratch.
"""

from __future__ import annotations

import pytest
from pytest_intent import intent

from studio.adapters.outbound.github_repo.github_app_writer import GithubAppWriter

_API = "https://api.github.com"
_REPO_URL = "https://github.com/Test-Org/alpha-app"
_FILES = {"README.md": "# alpha\n", "k8s/Chart.yaml": "name: alpha\n"}


class _Api:
    """Records every call and answers from a scripted table.

    A list value scripts successive answers for one fragment (each call
    consumes the next entry); anything else answers every call the same.
    """

    def __init__(self, responses: dict[str, object] | None = None) -> None:
        self.writes: list[tuple[str, str, dict]] = []
        self.gets: list[str] = []
        self.deletes: list[str] = []
        self.delete_ok = True
        self._responses = responses or {}

    def write_json(self, method: str, url: str, payload: dict) -> object | None:
        self.writes.append((method, url, payload))
        return self._answer(url)

    def get_json(self, url: str) -> object | None:
        self.gets.append(url)
        return self._answer(url)

    def _answer(self, url: str) -> object | None:
        for fragment, response in self._responses.items():
            if fragment in url:
                if isinstance(response, list):
                    return response.pop(0) if response else None
                return response
        return None

    def delete(self, url: str) -> bool:
        self.deletes.append(url)
        return self.delete_ok


def _writer(api: _Api, monkeypatch: pytest.MonkeyPatch) -> GithubAppWriter:
    writer = GithubAppWriter("token")
    monkeypatch.setattr(writer, "_write_json", api.write_json)
    monkeypatch.setattr(writer, "_get_json", api.get_json)
    monkeypatch.setattr(writer, "_delete", api.delete)
    return writer


@intent("INT-SCAFFOLD-001")
def test_create_repository_auto_inits_so_the_seed_can_land(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _Api({"/orgs/": {"full_name": "example-org/alpha-app"}})
    assert _writer(api, monkeypatch).create_repository(
        org="example-org", name="alpha-app", description="d"
    )
    _, url, payload = api.writes[0]
    assert "/orgs/example-org/repos" in url
    # Without this the repository has no commits and every git-data write 409s.
    assert payload["auto_init"] is True
    assert payload["private"] is True
    assert payload["description"] == "d"


@intent("INT-SCAFFOLD-001")
def test_seed_branch_parents_the_head_and_updates_the_ref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _Api(
        {
            "/git/ref/heads/main": {"object": {"sha": "head-sha"}},
            "/git/trees": {"sha": "tree-sha"},
            "/git/commits": {"sha": "commit-sha"},
            "/git/refs/heads/main": {"ref": "refs/heads/main"},
        }
    )
    assert _writer(api, monkeypatch).seed_branch(
        repo_url=_REPO_URL, branch="main", files=_FILES, message="feat: scaffold"
    )
    assert api.gets == ["https://api.github.com/repos/Test-Org/alpha-app/git/ref/heads/main"]
    by_url = {url: (method, payload) for method, url, payload in api.writes}

    tree = next(p for u, (m, p) in by_url.items() if u.endswith("/git/trees"))
    # No base_tree: the branch ends up holding exactly these files, so nothing
    # of the auto-init commit (its README) survives the seed.
    assert "base_tree" not in tree
    assert {entry["path"] for entry in tree["tree"]} == set(_FILES)

    commit = next(p for u, (m, p) in by_url.items() if u.endswith("/git/commits"))
    assert commit["parents"] == ["head-sha"]  # ordinary fast-forward, never a force

    method, _ = next((m, p) for u, (m, p) in by_url.items() if u.endswith("/git/refs/heads/main"))
    assert method == "PATCH"  # the ref exists; creating it would 422


@intent("INT-SCAFFOLD-001")
def test_seed_branch_rides_out_the_auto_init_race(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """auto_init's commit lands after create_repository returns, so the first
    head reads 404; one losing read must not cost the caller the scaffold."""
    api = _Api(
        {
            "/git/ref/heads/main": [None, None, {"object": {"sha": "head-sha"}}],
            "/git/trees": {"sha": "tree-sha"},
            "/git/commits": {"sha": "commit-sha"},
            "/git/refs/heads/main": {"ref": "refs/heads/main"},
        }
    )
    writer = _writer(api, monkeypatch)
    slept: list[float] = []
    monkeypatch.setattr(writer, "_sleep", slept.append)
    assert writer.seed_branch(
        repo_url=_REPO_URL, branch="main", files=_FILES, message="feat: scaffold"
    )
    assert len(api.gets) == 3  # polled until the auto-init head appeared
    assert len(slept) == 2  # waits between reads, never before the first
    commit = next(p for m, u, p in api.writes if u.endswith("/git/commits"))
    assert commit["parents"] == ["head-sha"]


@intent("INT-SCAFFOLD-001")
def test_seed_branch_without_a_readable_head_is_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _Api({"/git/trees": {"sha": "tree-sha"}})  # the head read answers nothing
    writer = _writer(api, monkeypatch)
    slept: list[float] = []
    monkeypatch.setattr(writer, "_sleep", slept.append)
    assert not writer.seed_branch(
        repo_url=_REPO_URL, branch="main", files=_FILES, message="feat: scaffold"
    )
    assert api.writes == []  # refuses before writing anything
    assert len(api.gets) == 5  # the poll is bounded, not forever


@intent("INT-SCAFFOLD-001")
def test_create_orphan_branch_still_creates_a_parentless_ref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The deploy-branch leg is unchanged by the seeding split."""
    api = _Api(
        {
            "/git/trees": {"sha": "tree-sha"},
            "/git/commits": {"sha": "commit-sha"},
            "/git/refs": {"ref": "refs/heads/deploy-example"},
        }
    )
    assert _writer(api, monkeypatch).create_orphan_branch(
        repo_url=_REPO_URL, branch="deploy-example", files=_FILES, message="chore: deploy"
    )
    by_url = {url: (method, payload) for method, url, payload in api.writes}
    commit = next(p for u, (m, p) in by_url.items() if u.endswith("/git/commits"))
    assert commit["parents"] == []
    method, payload = next(
        (m, p) for u, (m, p) in by_url.items() if u.endswith("/git/refs")
    )
    assert method == "POST"
    assert payload["ref"] == "refs/heads/deploy-example"
    assert api.gets == []  # an orphan needs no head to build on


@intent("INT-SCAFFOLD-001")
def test_a_refused_write_is_kept_verbatim_for_the_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The adapter is the only layer that ever sees the host's reason."""
    writer = GithubAppWriter("token")
    body = (
        "{'message': 'refusing to allow a Personal Access Token to create or "
        "update workflow `.github/workflows/build.yml` without `workflow` scope'}"
    )
    writer._record("PATCH", f"{_API}/repos/o/a/git/refs/heads/main", 422, body)
    said = writer.last_failure()
    assert said.startswith("PATCH repos/o/a/git/refs/heads/main answered 422:")
    assert "without `workflow` scope" in said
    assert _API not in said  # the shared prefix is noise in an operator's message


def test_delete_repository_reports_a_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _Api()
    api.delete_ok = False
    writer = _writer(api, monkeypatch)
    assert not writer.delete_repository(org="example-org", name="alpha-app")
    api.delete_ok = True
    assert writer.delete_repository(org="example-org", name="alpha-app")
    assert api.deletes[-1].endswith("/repos/example-org/alpha-app")
