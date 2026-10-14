"""create_app_repo: a repo born carrying the whole app contract.

The scaffold is the REF-Foundry contract rendered, so these tests assert the
same mechanical facts the shared ci workflow's conformance job checks: a repo
built from this template is green in its own CI from the first push.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml
from fastapi.testclient import TestClient
from pytest_intent import intent

from studio.adapters.inbound.http.app import create_app
from studio.container import Container
from studio.domain.services.app_repo_scaffold import render_app_repo_scaffold
from studio.domain.services.events_grant import render_events_grant
from tests.conftest import FakeGitPr, FakeProbe, StubConformance


class _Reader:
    def __init__(self, exists: bool | None = False) -> None:
        self._exists = exists

    def deploy_values(self, *, repo_url: str, branch: str, path: str) -> dict | None:
        return None

    def repo_exists(self, *, repo_url: str) -> bool | None:
        return self._exists

    def default_branch(self, *, repo_url: str) -> str | None:
        return None

    def file_text(self, *, repo_url: str, branch: str, path: str) -> str | None:
        return None

    def branch_paths(self, *, repo_url: str, branch: str) -> frozenset[str] | None:
        return None


class _Writer:
    """A repo host that keeps GitHub's own preconditions.

    The point of the bookkeeping: a fake that answers True unconditionally
    cannot fail, so it once let a scaffold ship that could never write a
    single file - the git-data API refuses a repository with no commits (409,
    "Git Repository is empty") and nothing in the suite modelled that. Here a
    repo has commits only once it is created with auto-init, orphan-branch
    creation needs history and an absent ref, and seeding needs a ref that is
    already there. Wire a leg wrongly and a test goes red instead of a repo.
    """

    def __init__(
        self,
        *,
        can_delete: bool = True,
        seed_fails: bool = False,
        failure: str = "",
    ) -> None:
        self.repositories: list[dict[str, str]] = []
        self.branches: list[dict[str, object]] = []
        self.deleted: list[str] = []
        self._can_delete = can_delete
        self._seed_fails = seed_fails
        self._failure = failure
        self._refs: dict[str, set[str]] = {}  # repo name -> existing branches

    def last_failure(self) -> str:
        return self._failure

    @staticmethod
    def _name(repo_url: str) -> str:
        return repo_url.rstrip("/").rsplit("/", 1)[-1]

    def create_repository(self, *, org: str, name: str, description: str) -> bool:
        self.repositories.append({"name": name, "description": description})
        # auto-init: the repository is born with a commit on its default branch,
        # which is the whole reason the git-data API will speak to it later.
        self._refs[name] = {"main"}
        return True

    def delete_repository(self, *, org: str, name: str) -> bool:
        if not self._can_delete:
            return False
        self.deleted.append(name)
        self._refs.pop(name, None)
        self.repositories = [r for r in self.repositories if r["name"] != name]
        return True

    def latest_semver_tag(self, *, owner: str, package: str) -> str | None:
        return None

    def create_orphan_branch(
        self, *, repo_url: str, branch: str, files: dict[str, str], message: str
    ) -> bool:
        refs = self._refs.get(self._name(repo_url))
        if not refs:
            return False  # 409: the git-data API refuses an empty repository
        if branch in refs:
            return False  # the ref already exists; this call only creates
        refs.add(branch)
        self.branches.append(
            {"repo_url": repo_url, "branch": branch, "files": files, "message": message}
        )
        return True

    def seed_branch(
        self, *, repo_url: str, branch: str, files: dict[str, str], message: str
    ) -> bool:
        if self._seed_fails:
            return False
        refs = self._refs.get(self._name(repo_url))
        if not refs or branch not in refs:
            return False  # nothing to fast-forward from
        self.branches.append(
            {"repo_url": repo_url, "branch": branch, "files": files, "message": message}
        )
        return True


def _client(platform_root: Path, reader: _Reader, writer: _Writer | None) -> TestClient:
    container = Container(
        platform_root=platform_root,
        conformance=StubConformance(),
        git_pr=FakeGitPr(),
        http_probe=FakeProbe(),
        app_repo=reader,
        app_writer=writer,
    )
    return TestClient(create_app(container))


_REQUEST = {
    "name": "gamma-app",
    "display_name": "Gamma App",
    "description": "The gamma application",
}


class TestCreateAppRepo:
    @intent("INT-SCAFFOLD-001")
    def test_creates_repo_main_and_deploy_branch(self, platform_root: Path) -> None:
        writer = _Writer()
        response = _client(platform_root, _Reader(False), writer).post(
            "/api/repos/app", json=_REQUEST
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["repo_url"] == (
            "https://github.com/Test-Org/gamma-app"
        )
        assert body["image_components"] == ["app", "docs"]
        assert body["deploy_branch"] == "deploy-test"
        assert writer.repositories == [
            {"name": "gamma-app", "description": "The gamma application"}
        ]
        branches = {b["branch"]: b for b in writer.branches}
        assert set(branches) == {"main", "deploy-test"}
        # The deploy branch pins the deterministic first release.
        deploy = branches["deploy-test"]["files"]
        assert "version: 1.0.0" in deploy["prod/Chart.yaml"]
        assert "tag: 1.0.0" in deploy["prod/values.yaml"]
        assert (
            "repository: ghcr.io/test-org/gamma-app-app"
            in deploy["prod/values.yaml"]
        )
        # The main seed is a conventional feat commit: the release trigger.
        assert branches["main"]["message"].startswith("feat: ")

    def test_the_repository_may_be_named_differently_from_the_app(
        self, platform_root: Path
    ) -> None:
        """The repository is a fact of its own (INT-SKELETON-001). An
        organisation shared with unrelated work prefixes its repositories, while
        the app keeps the clean name that becomes its namespace, hostname, chart
        and packages. With one name for both, a scaffold could only ever produce
        a repository named for the app - so either the org's convention breaks or
        the prefix lands in every hostname."""
        writer = _Writer()
        response = _client(platform_root, _Reader(False), writer).post(
            "/api/repos/app", json={**_REQUEST, "repo": "fleet-gamma-app"}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        # The repository takes the prefixed name...
        assert body["repo_url"] == "https://github.com/Test-Org/fleet-gamma-app"
        assert writer.repositories == [
            {"name": "fleet-gamma-app", "description": "The gamma application"}
        ]
        # ...while every platform-keyed artifact stays the app's own name.
        assert body["name"] == "gamma-app"
        deploy = {b["branch"]: b for b in writer.branches}["deploy-test"]["files"]
        assert "repository: ghcr.io/test-org/gamma-app-app" in deploy["prod/values.yaml"]

    def test_existing_repository_is_409(self, platform_root: Path) -> None:
        response = _client(platform_root, _Reader(True), _Writer()).post(
            "/api/repos/app", json=_REQUEST
        )
        assert response.status_code == 409

    def test_no_writer_wired_is_502(self, platform_root: Path) -> None:
        response = _client(platform_root, _Reader(False), None).post(
            "/api/repos/app", json=_REQUEST
        )
        assert response.status_code == 502

    @intent("INT-SCAFFOLD-001")
    def test_main_is_seeded_not_orphaned(self, platform_root: Path) -> None:
        """main exists the moment the repo does (auto-init), so the seed must
        update that ref; creating one would refuse, which is exactly how a repo
        once shipped carrying no contract at all."""
        writer = _Writer()
        response = _client(platform_root, _Reader(False), writer).post(
            "/api/repos/app", json=_REQUEST
        )
        assert response.status_code == 200, response.text
        main = next(b for b in writer.branches if b["branch"] == "main")
        # The whole rendered contract landed, not a token file.
        assert ".github/workflows/build.yml" in main["files"]
        assert "k8s/templates/httproute.yaml" in main["files"]
        assert len(main["files"]) > 20

    @intent("INT-SCAFFOLD-001")
    def test_a_failed_seed_takes_the_repository_with_it(self, platform_root: Path) -> None:
        writer = _Writer(seed_fails=True)
        response = _client(platform_root, _Reader(False), writer).post(
            "/api/repos/app", json=_REQUEST
        )
        assert response.status_code == 502
        assert writer.deleted == ["gamma-app"]
        assert writer.repositories == []  # nothing half-built survives
        assert "was removed" in response.json()["detail"]

    @intent("INT-SCAFFOLD-001")
    def test_the_refusal_carries_the_hosts_own_words(self, platform_root: Path) -> None:
        """A standing refusal must name itself, not read as bad luck.

        The scaffold carries .github/workflows/build.yml, so a classic token
        without `workflow` scope fails this write identically every time. Told
        only "retry", an operator retries; told what the host said, they fix
        the credential. That cost three rounds once.
        """
        said = (
            "PATCH repos/O/gamma-app/git/refs/heads/main answered 422: refusing to "
            "allow a Personal Access Token to create or update workflow "
            "`.github/workflows/build.yml` without `workflow` scope"
        )
        writer = _Writer(seed_fails=True, failure=said)
        response = _client(platform_root, _Reader(False), writer).post(
            "/api/repos/app", json=_REQUEST
        )
        assert response.status_code == 502
        detail = response.json()["detail"]
        assert "without `workflow` scope" in detail
        assert "422" in detail
        assert "retry" not in detail  # never advise a retry for a standing refusal

    @intent("INT-SCAFFOLD-001")
    def test_a_failed_rollback_names_the_surviving_repository(
        self, platform_root: Path
    ) -> None:
        """A rollback that cannot run must not read like one that did."""
        writer = _Writer(seed_fails=True, can_delete=False)
        response = _client(platform_root, _Reader(False), writer).post(
            "/api/repos/app", json=_REQUEST
        )
        assert response.status_code == 502
        assert writer.deleted == []
        detail = response.json()["detail"]
        assert "survives EMPTY" in detail
        assert "delete it by hand" in detail


class TestScaffoldMeetsTheContract:
    """The scaffold against the app-contract checks it must pass in CI."""

    def setup_method(self) -> None:
        self.files = render_app_repo_scaffold(
            app="gamma-app",
            display_name="Gamma App",
            description="The gamma application",
            registry="ghcr.io/test-org",
            org="Test-Org",
            ci_repo="ci",
        )

    @intent("INT-SCAFFOLD-001")
    def test_every_declared_claim_is_attested(self) -> None:
        """The "green from the first push" promise, held to.

        The shared workflow's conformance job runs csd-intent, which fails an
        unattested claim - so a scaffold that ships an intent.yaml without the
        test carrying its marker is red on the first push of every repo it ever
        creates. It shipped that way: two claims, no tests, and the file-shape
        assertions here could not see it because a marker's absence is not a
        missing file.
        """
        markers = "\n".join(
            text
            for path, text in self.files.items()
            if "test" in path and path.endswith((".py", ".ts", ".tsx", ".js", ".jsx"))
        )
        assert markers, "the scaffold ships no test files at all"
        for path, text in self.files.items():
            if not path.endswith("intent.yaml"):
                continue
            claims = [
                line.split(":", 1)[0].strip()
                for line in text.splitlines()
                if line.startswith("INT-") and line.rstrip().endswith(":")
            ]
            assert claims, f"{path} declares no claim"
            for claim in claims:
                assert f'"{claim}"' in markers or f"'{claim}'" in markers, (
                    f"{path}: {claim} has no @intent / intent() marker in any rendered "
                    "test file, so csd-intent fails this repo on its first push"
                )

    @intent("INT-SCAFFOLD-001")
    def test_the_docs_image_resolves_the_registry_with_no_credential(self) -> None:
        """The docs image installs its intent runtime with no credential at all.

        The meta-test's runtime is a @psa-department-of-engineering/* package.
        Those lived on GitHub Packages, which needs auth to RESOLVE a package -
        not merely to download it, so --omit=dev did not dodge it, as proxiverso's
        build proved twice. They are on the public npm registry now (csd-library
        ADR-0003), so a scaffolded repo carries no .npmrc, mounts no build secret,
        and - the point - can be forked and built by someone with no PSA token.
        """
        dockerfile = self.files["docs/Dockerfile"]
        assert "--mount=type=secret" not in dockerfile
        assert "COPY package.json .npmrc" not in dockerfile
        assert "docs/.npmrc" not in self.files
        # INT-FOUNDRY-039: the repo never provides a packages token itself.
        assert "NODE_AUTH_TOKEN" not in self.files[".github/workflows/build.yml"]
        package = json.loads(self.files["docs/package.json"])
        assert "@psa-department-of-engineering/vitest-intent" in package["devDependencies"]

    def test_devops_contract(self) -> None:
        assert "devops/Dockerfile" in self.files
        compose = self.files["devops/docker-compose.yml"]
        assert "devops/Dockerfile" in compose  # INT-FOUNDRY-003
        parsed = yaml.safe_load(compose)
        service = parsed["services"]["app"]
        assert service["image"] == "gamma-app-app:latest"  # the released package
        assert not any("push" in p.lower() and "image" in p.lower() for p in self.files)

    def test_ci_caller_is_the_shared_workflow(self) -> None:
        build = self.files[".github/workflows/build.yml"]
        assert (
            "uses: Test-Org/ci/.github/workflows/build.yml@main" in build
        )  # INT-FOUNDRY-013
        assert "NODE_AUTH_TOKEN" not in build  # INT-FOUNDRY-039

    def test_the_ci_caller_names_the_app_it_ships(self) -> None:
        """INT-SKELETON-001: the caller passes app-name rather than inheriting the
        shared workflow's repository-name default.

        Everything the build is judged against is keyed on the fleet name - the
        app's Gateway, keycloak-<app>, pg-app-<app> - and so is every package it
        publishes. On a fleet whose repositories carry a prefix the repo name is
        not the app name, and the inherited default failed the conformance gate
        on the app's own chart while publishing packages the deploy branch does
        not watch.
        """
        build = self.files[".github/workflows/build.yml"]
        assert "app-name: gamma-app" in build
        assert build.index("with:") < build.index("permissions:")

    def test_the_scaffold_ships_an_app_owned_test_workflow(self) -> None:
        """INT-FOUNDRY-063: a scaffolded repo has a PR gate on day one.

        build.yml is shared so release cannot drift; a test suite is per-app, so
        there is nothing to share - but the FILE is contract, because without it a
        contributor's PR (a fork's especially) meets no gate at all. It carries
        the intent audit, the one gate every app repo has by contract, and a
        runner for each suite the scaffold ships - the audit alone only proves a
        marker exists, so without the runners both intent.yaml claims shipped
        `active` attested by tests nothing ever ran (#21).
        """
        test = self.files[".github/workflows/test.yml"]
        parsed = yaml.safe_load(test)
        on = parsed.get("on", parsed.get(True))
        assert "pull_request" in on, "a PR must meet a gate"
        assert "csd-intent ." in test
        # Every suite the scaffold ships is run by a job, not merely audited:
        # the walking skeleton's pytest suite and the docs vitest meta-test.
        assert "csd-pytest-intent~=" in test, "#21: the pytest suite needs its runtime"
        assert "pytest tests" in test, "#21: the shipped pytest suite must run"
        assert "npm test" in test, "#21: the shipped docs meta-test must run"
        # It is app-owned, never a caller of the shared build workflow.
        assert "ci/.github/workflows/build.yml" not in test
        # A fork gets a runner it can actually reach.
        assert "github.event.repository.fork" in test

    def test_chart_contract(self) -> None:
        values = yaml.safe_load(self.files["k8s/values.yaml"])
        assert values["paused"] is False  # INT-FOUNDRY-030
        assert "host" in values  # INT-FOUNDRY-046
        assert values["gateway"]["namespace"] == "network"
        deployments = [
            text
            for text in self.files.values()
            if isinstance(text, str) and "kind: Deployment" in text
        ]
        assert deployments
        assert all("imagePullSecrets" in d for d in deployments)  # INT-FOUNDRY-045
        app_deployment = self.files["k8s/templates/deployment.yaml"]
        assert ".Values.paused" in app_deployment  # INT-FOUNDRY-030
        docs_deployment = self.files["k8s/templates/docs-deployment.yaml"]
        assert re.search(r"app\.kubernetes\.io/name:.*-docs", docs_deployment)  # 048
        docs_service = self.files["k8s/templates/docs-service.yaml"]
        assert "name: gamma-app-docs" in docs_service  # INT-FOUNDRY-056
        route = self.files["k8s/templates/httproute.yaml"]
        assert "name: {{ .Chart.Name }}" in route  # INT-FOUNDRY-046: own Gateway
        assert "hostnames:" in route

    def test_the_events_block_names_what_the_grant_mints(self) -> None:
        """The scaffold ships the event-bus consumer off, carrying the two
        Secret names the grant's own Jobs will create for this app, so adopting
        the grant is flipping `enabled` and nothing else. Held against the
        grant renderer rather than a literal: the scaffold and the grant are
        two renders of one contract, and this is the test that keeps them from
        drifting apart (platform-studio#23)."""
        values = yaml.safe_load(self.files["k8s/values.yaml"])
        events = values["events"]
        assert events["enabled"] is False
        grant = render_events_grant("gamma-app", ("gamma",))
        assert f"kubectl create secret generic {events['seedSecret']} -n gamma-app" in grant
        assert f"kubectl create secret generic {events['jwtSecret']} -n messaging" in grant
        deployment = self.files["k8s/templates/deployment.yaml"]
        # The two halves are assembled into the one file a NATS client reads,
        # and neither mount is optional: a missing grant holds the pod.
        assert "assemble-nats-creds" in deployment
        assert ".Values.events.seedSecret" in deployment
        assert ".Values.events.jwtSecret" in deployment
        assert "optional: true" not in deployment
        assert "-----BEGIN USER NKEY SEED-----" in deployment

    def test_docs_contract(self) -> None:
        config = self.files["docs/astro.config.mjs"]
        assert "DOCS_BASE" in config and re.search(r"base\s*:", config)  # 018
        dockerfile = self.files["docs/Dockerfile"]
        assert "ARG DOCS_BASE" in dockerfile
        assert re.search(r"html/?\$\{?DOCS_BASE\}?", dockerfile)
        types = set()
        for path, text in self.files.items():
            if path.startswith("docs/src/content/docs/"):
                m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
                for line in (m.group(1).splitlines() if m else []):
                    if line.strip().startswith("type:"):
                        types.add(line.split(":", 1)[1].strip())
        assert types == {"Overview"}
        assert "docs/src/content/docs/reference.md" not in self.files
        overview = self.files["docs/src/content/docs/index.md"]
        assert "flowchart TB" in overview and "## Read next" in overview
        assert "<one-paragraph" not in overview
        labels = re.findall(r"label: '([^']+)'", config)
        assert labels == ["Overview", "Modules", "Flows", "Operations", "Reference", "Decisions"]
        assert "INT-STARLIGHT-" in self.files["docs/intent.yaml"]  # INT-FOUNDRY-022

    def test_intent_and_hygiene_contract(self) -> None:
        intent = yaml.safe_load(self.files["intent.yaml"])
        claims = {
            k: v
            for k, v in intent.items()
            if k.startswith("INT-") and v.get("statement") and v.get("status")
        }
        assert claims  # INT-FOUNDRY-009
        hook = self.files[".pre-commit-config.yaml"].lower()
        assert "commit-msg" in hook and "conventional" in hook  # INT-FOUNDRY-019
        # The local guard mirrors BOTH rules ci's check-commit-hygiene enforces,
        # not just the conventional subject. The co-author half is the one that
        # fires: a trailer caught only in CI is caught after the push, with the
        # commit unremovable short of a history rewrite and the release job held
        # behind a red build. So the guard is asserted by what it does - the
        # rendered pattern is run against a message carrying the trailer - rather
        # than by the hook id being present.
        config = yaml.safe_load(self.files[".pre-commit-config.yaml"])
        # A commit-msg hook git is never told to call is not a guard. `pre-commit
        # install` wires the pre-commit stage alone, so without this key the
        # clone gets .git/hooks/pre-commit and nothing else, and BOTH commit-msg
        # hooks are inert while the config still parses as if they were live.
        assert "commit-msg" in config.get("default_install_hook_types", [])
        guards = [
            h
            for repo in config["repos"]
            for h in repo["hooks"]
            if h.get("language") == "pygrep" and "commit-msg" in h.get("stages", [])
        ]
        assert len(guards) == 1, "no local commit-msg guard for the co-author rule"
        guard = guards[0]
        assert "--ignore-case" in guard.get("args", []), "the trailer's casing varies"
        pattern = re.compile(guard["entry"], re.IGNORECASE)
        # The last two are what ci's own [[:space:]] class accepts: the local
        # half passing what the gate rejects is the drift this pair exists to
        # prevent.
        for trailer in (
            "Co-Authored-By: Claude Opus 5",
            "co-authored-by: A <a@b>",
            "\tCo-authored-by: A <a@b>",
            "\vCo-authored-by: A <a@b>",
            "\fCo-authored-by: A <a@b>",
        ):
            assert pattern.search(trailer), f"the guard lets {trailer!r} through"
        assert not pattern.search("fix: a subject mentioning co-authored-by: inline")
        readme = self.files["README.md"].lower()
        for section in ("run with docker", "develop without docker", "layout"):
            assert section in readme  # INT-FOUNDRY-007
        # The README is the first thing a committer reads; it names the commit
        # convention and where it is documented, so the rule is met before the
        # hook or CI ever has to refuse a message.
        assert "## commits" in readme and "commit convention" in readme
        assert ".env.example" in self.files  # INT-FOUNDRY-008
        # A repo is born ignoring what its own tooling generates. The scaffold
        # ships the trees that produce these: docs/ (npm install -> node_modules,
        # astro build -> dist + .astro) and tests/ (pytest -> __pycache__). Absent
        # this file they are untracked-and-not-ignored and the first `git add -A`
        # commits them, which is how every pre-template repo went.
        ignored = self.files[".gitignore"].splitlines()
        for pattern in ("node_modules/", "dist/", ".astro/", "__pycache__/", ".env"):
            assert pattern in ignored, f"a scaffolded repo commits {pattern}"

    def test_digit_leading_app_gets_the_svc_prefixed_docs_service(self) -> None:
        files = render_app_repo_scaffold(
            app="2fast",
            display_name="Too Fast",
            description="Digit-leading app",
            registry="ghcr.io/test-org",
        )
        assert "name: svc-2fast-docs" in files["k8s/templates/docs-service.yaml"]


# Ordinary English, carrying every character the scaffold's target syntaxes read
# structurally: a colon-space (a YAML mapping), an apostrophe and quotes (YAML
# and JavaScript literals), an ampersand and angle brackets (HTML).
_FREE_TEXT_DISPLAY = 'Rafael\'s "UCN" Helper: v2'
_FREE_TEXT_DESCRIPTION = "A companion for UCN: roster, routes & <the maths>"


class TestCallerTextCannotCorruptTheScaffold:
    """The caller's own words land as data in every syntax the scaffold writes.

    ucn-helper was scaffolded with a description reading "A companion for ...:
    roster, routes, and the maths" and its own first CI run went red: the
    colon-space turned k8s/Chart.yaml's description into a mapping, and the
    check that parses the chart raised yaml.scanner.ScannerError. That is the
    one outcome this act exists to rule out, so the rendered form of the
    caller's words is pinned here per target syntax, not per file that broke.
    """

    def setup_method(self) -> None:
        self.files = render_app_repo_scaffold(
            app="gamma-app",
            display_name=_FREE_TEXT_DISPLAY,
            description=_FREE_TEXT_DESCRIPTION,
            registry="ghcr.io/test-org",
        )

    @intent("INT-SCAFFOLD-002")
    def test_every_rendered_yaml_parses(self) -> None:
        """The Helm templates are excluded: their {{ }} is not YAML until Helm
        renders it, and no caller text reaches them."""
        documents = [
            path
            for path in self.files
            if path.endswith((".yaml", ".yml")) and not path.startswith("k8s/templates/")
        ]
        assert "k8s/Chart.yaml" in documents
        for path in documents:
            try:
                parsed = yaml.safe_load(self.files[path])
            except yaml.YAMLError as error:
                raise AssertionError(f"{path} is not YAML as rendered: {error}") from error
            assert parsed, f"{path} rendered empty"

    @intent("INT-SCAFFOLD-002")
    def test_the_chart_reads_back_the_description_whole(self) -> None:
        chart = yaml.safe_load(self.files["k8s/Chart.yaml"])
        assert chart["description"] == _FREE_TEXT_DESCRIPTION
        assert chart["name"] == "gamma-app"

    @intent("INT-SCAFFOLD-002")
    def test_the_docs_frontmatter_reads_back_the_callers_words_whole(self) -> None:
        for path, text in self.files.items():
            if not path.startswith("docs/src/content/docs/"):
                continue
            block = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
            assert block, f"{path} carries no frontmatter"
            try:
                front = yaml.safe_load(block.group(1))
            except yaml.YAMLError as error:
                raise AssertionError(f"{path} frontmatter is not YAML: {error}") from error
            assert front["title"], f"{path} frontmatter carries no title"
            if path.endswith("index.md"):
                assert front["title"] == _FREE_TEXT_DISPLAY
                assert front["summary"] == _FREE_TEXT_DESCRIPTION

    @intent("INT-SCAFFOLD-002")
    def test_the_docs_config_carries_the_title_as_a_javascript_literal(self) -> None:
        """An apostrophe is ordinary in a display name and ends a single-quoted
        literal; the Astro config is JavaScript, so the title is one."""
        literal = re.search(r"title:\s*(\".*\"),", self.files["docs/astro.config.mjs"])
        assert literal, "the docs config carries no title literal"
        assert json.loads(literal.group(1)) == _FREE_TEXT_DISPLAY

    @intent("INT-SCAFFOLD-002")
    def test_the_landing_page_escapes_the_callers_words(self) -> None:
        page = self.files["app/index.html"]
        assert "roster, routes &amp; &lt;the maths&gt;" in page
        assert _FREE_TEXT_DESCRIPTION not in page  # never raw in markup
        assert f"<title>{_FREE_TEXT_DISPLAY}</title>" in page  # a text node keeps quotes

    @intent("INT-SCAFFOLD-002")
    def test_a_placeholder_in_the_callers_words_is_not_substituted(self) -> None:
        """The caller's words are the end of the substitution, not more input."""
        files = render_app_repo_scaffold(
            app="gamma-app",
            display_name="<app> Runner",
            description="Renders <display> for <app>",
            registry="ghcr.io/test-org",
        )
        readme = files["README.md"]
        assert "# <app> Runner" in readme
        assert "Renders <display> for <app>" in readme


def test_app_scaffold_qualifies_foreign_decision_ids() -> None:
    files = render_app_repo_scaffold(
        app="example", display_name="Example", description="Example app",
        registry="ghcr.io/example-org",
    )
    for path, text in files.items():
        assert not re.search(r"(?<!platform )\bADR-\d{3}(?!\d)", text), path
