"""The app's promotion contract: devops/promotion.yaml, app-owned.

The contract declares where this app's proven releases move beyond the entry
environment. Each target carries three definitions, written out in full:
``door`` (how the write is submitted), ``terms`` (what is written and what
deployed means), and ``acceptance`` (what proven-there means). Nothing is
resolved by an engine at run time - what the file says is what happens - and
credentials are named here but held by the platform, never stored in any
repository.

Two target kinds exist. ``environment`` names a manual environment of an
install we run: the door is a commit to the app's own ``deploy-<install>``
branch, the terms are the version (image tags plus the chart pin), deployed
when that environment serves them. ``repository`` names another
organization's repository: the door is a pull request theirs to review, the
terms are source, deployed when the merge lands.

The scaffold ships the file with an empty target list and the two kinds
written out as comments: a new app promotes nowhere until a hand declares a
destination, and the shape travels with the file it will be declared in.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

import yaml

__all__ = [
    "CONTRACT_PATH",
    "PromotionTarget",
    "parse_promotion_contract",
    "render_promotion_contract",
]

CONTRACT_PATH = "devops/promotion.yaml"

_NAME = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
_KINDS = ("environment", "repository")

_SCAFFOLD = """\
# The app's promotion contract: where proven releases move beyond the entry
# environment. Each target carries its door (how the write is submitted),
# terms (what is written, and what deployed means) and acceptance (what
# proven-there means), written out in full; nothing is resolved by an engine
# at run time. Credentials are named here and held by the platform, never
# stored in any repository.
#
# targets:
#   - name: example-prod          # an environment of an install we run
#     kind: environment
#     install: example
#     environment: prod           # in that install's declared list; never its entry
#     door: commit                # to this repo's deploy-example branch
#     terms: version              # image tags + chart pin; deployed when it serves them
#     acceptance: probe           # or: none (closes at deployed), or suite
#   - name: example-qa            # a suite verdict is READ where it is published
#     kind: environment
#     install: example
#     environment: qa
#     door: commit
#     terms: version
#     acceptance: suite           # the app's own integrated suite
#     suite: https://ci.example/api/sit/latest
#     suite_pass: '"result":"passed"'   # a 200 is transport, not a pass
#   - name: partner               # another organization's repository
#     kind: repository
#     repo: their-org/their-repo
#     branch: main
#     credential: partner-pair    # a named secret the platform holds
#     door: pull-request          # theirs to review; the merge lands it
#     terms: source
#     acceptance: none            # or: probe: https://their-hostname.example
targets: []
"""


@dataclass(frozen=True)
class PromotionTarget:
    """One declared destination, every definition explicit."""

    name: str
    kind: str
    door: str
    terms: str
    acceptance: str
    install: str = ""
    environment: str = ""
    repo: str = ""
    branch: str = ""
    credential: str = ""
    probe_url: str = ""
    # A suite acceptance is READ where it publishes, never dispatched: who
    # executes it is outside the contract, because a destination we can write
    # to may be on a network nothing here can reach (REF-Promotion section 3).
    suite_url: str = ""
    suite_pass: str = ""


def render_promotion_contract() -> str:
    """The scaffolded contract: the shape as comments, no target declared."""
    return _SCAFFOLD


#: What proven-there may mean. A suite and a probe are both READ; they differ in
#: what the answer means, not in who runs it.
_ACCEPTANCE = ("suite", "probe", "none")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(f"devops/promotion.yaml: {message}")


def parse_promotion_contract(text: str) -> tuple[PromotionTarget, ...]:
    """The declared targets, validated; a malformed contract raises.

    Loud on malformation for the same reason the environments declaration is:
    a hand wrote something, and silently skipping it would promote against a
    contract the hand did not declare.
    """
    raw = yaml.safe_load(text) or {}
    _require(isinstance(raw, Mapping), "the contract is a mapping with a targets list")
    entries = raw.get("targets")
    _require(isinstance(entries, list), "targets: must be a list (empty is fine)")
    targets: list[PromotionTarget] = []
    for entry in entries:
        _require(isinstance(entry, Mapping), f"target {entry!r} is not a mapping")
        name = str(entry.get("name") or "")
        _require(
            bool(_NAME.match(name)),
            f"target name {name!r} is not a lowercase DNS label",
        )
        _require(
            name not in {t.name for t in targets},
            f"target {name!r} is declared twice",
        )
        kind = str(entry.get("kind") or "")
        _require(kind in _KINDS, f"target {name!r}: kind must be one of {_KINDS}")
        acceptance_raw = entry.get("acceptance", "none")
        probe_url = ""
        if isinstance(acceptance_raw, Mapping):
            probe_url = str(acceptance_raw.get("probe") or "")
            _require(
                bool(probe_url),
                f"target {name!r}: a mapping acceptance carries probe: <url>",
            )
            acceptance = "probe"
        else:
            acceptance = str(acceptance_raw or "none")
        suite_url = str(entry.get("suite") or "")
        suite_pass = str(entry.get("suite_pass") or "")
        if kind == "environment":
            install = str(entry.get("install") or "")
            environment = str(entry.get("environment") or "")
            _require(
                bool(install) and bool(environment),
                f"target {name!r}: kind environment names install and environment",
            )
            door = str(entry.get("door") or "commit")
            _require(
                door == "commit",
                f"target {name!r}: an environment target's door is commit",
            )
            terms = str(entry.get("terms") or "version")
            _require(
                terms == "version",
                f"target {name!r}: an environment target's terms are version",
            )
            _require(
                acceptance in _ACCEPTANCE,
                f"target {name!r}: acceptance is one of {_ACCEPTANCE}",
            )
            _require(
                acceptance != "suite" or bool(suite_url),
                f"target {name!r}: a suite acceptance names where the verdict is "
                "published (suite: <url>)",
            )
            targets.append(
                PromotionTarget(
                    name=name,
                    kind=kind,
                    door=door,
                    terms=terms,
                    acceptance=acceptance,
                    install=install,
                    environment=environment,
                    probe_url=probe_url,
                    suite_url=suite_url,
                    suite_pass=suite_pass,
                )
            )
            continue
        repo = str(entry.get("repo") or "")
        branch = str(entry.get("branch") or "")
        credential = str(entry.get("credential") or "")
        _require(
            bool(repo) and bool(branch) and bool(credential),
            f"target {name!r}: kind repository names repo, branch and credential",
        )
        door = str(entry.get("door") or "pull-request")
        _require(
            door == "pull-request",
            f"target {name!r}: a repository target's door is pull-request",
        )
        terms = str(entry.get("terms") or "source")
        _require(
            terms == "source",
            f"target {name!r}: a repository target's terms are source",
        )
        _require(
            acceptance in _ACCEPTANCE,
            f"target {name!r}: acceptance is one of {_ACCEPTANCE}",
        )
        _require(
            acceptance != "suite" or bool(suite_url),
            f"target {name!r}: a suite acceptance names where the verdict is "
            "published (suite: <url>)",
        )
        targets.append(
            PromotionTarget(
                name=name,
                kind=kind,
                door=door,
                terms=terms,
                acceptance=acceptance,
                repo=repo,
                branch=branch,
                credential=credential,
                probe_url=probe_url,
                suite_url=suite_url,
                suite_pass=suite_pass,
            )
        )
    return tuple(targets)
