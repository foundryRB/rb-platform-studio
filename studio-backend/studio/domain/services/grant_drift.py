"""A grant's declared meaning against the template that rendered it.

Every capability grant is rendered from a canonical template keyed on the app
name and its host, so the template's own contribution is exactly reproducible.
Nothing ever re-derived it, though, and nothing compared it either: once
appended, a grant's bytes were frozen while the template moved on. A template
change reached existing grants only as a hand sweep across every install, which
is how the fleet came to carry a ``webOrigins`` the template had stopped meaning
(#123) and how a hand-added redirect URI survived long enough to be load-bearing
on one install and silently absent on another (#140).

Two things this deliberately is NOT, both learned the hard way.

It is not a **byte** comparison. Comments are not meaning, and a grant whose
declarations are identical but whose comment block predates a template edit is
not drifted in any sense worth reporting - reporting it makes the check noise on
first contact, and noise is what gets a check ignored.

It is not a claim that a grant is the template's to rewrite. A realm's ``users``
list **is** its access allowlist: people are admitted by hand, by design, and a
render keyed only on the app name cannot know them. Comparing them would report
every realm with a real user as drifted, and - far worse - would invite a
"repair" that deletes the people. That is not hypothetical: normalising the fleet
against the template proposed removing an admitted operator from two realms, and
only a semantic guard stopped it. Reconcile once deleted a live generator's Role
and RoleBinding exactly this way (#100). So the comparison covers what the
template OWNS, and team-owned keys are out of its reach by construction rather
than by anyone remembering.

The remaining question is honest and narrow: does the template's own contribution
still say what the template would say today?
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import yaml

from studio.domain.services.team_documents import split_by_concern

__all__ = ["GrantDrift", "TEAM_OWNED_REALM_KEYS", "grant_drift"]

# Realm keys the team owns, which a render keyed on the app name cannot produce
# and must never be judged against. ``users`` is the access allowlist; deleting
# an entry revokes a person's access to the app.
TEAM_OWNED_REALM_KEYS = frozenset({"users"})

_REALM_FILE = "realm.yaml"


@dataclass(frozen=True)
class GrantDrift:
    """One grant's template-owned declarations against one app's team folder.

    ``drifted`` names the concern files whose template-owned content no longer
    matches. ``absent`` is the whole grant being absent, which is not drift: an
    app with no realm has no identity grant to compare, and reporting that as a
    difference would make every app without a capability look broken.
    """

    app: str
    grant: str
    absent: bool
    drifted: tuple[str, ...]

    @property
    def in_sync(self) -> bool:
        return not self.absent and not self.drifted

    def summary(self) -> str:
        if self.absent:
            return f"{self.app}: no {self.grant} grant"
        if not self.drifted:
            return f"{self.app}: {self.grant} grant matches the canonical template"
        files = ", ".join(self.drifted)
        return (
            f"{self.app}: {self.grant} grant no longer matches the canonical template "
            f"in {files}; the difference is in what the template declares, not in "
            f"team-owned content such as the realm's user allowlist"
        )


def _strip_team_owned(document: Any) -> Any:
    """Drop the keys the team owns from a realm ConfigMap, in place of comparing them.

    The realm body is a YAML string inside the ConfigMap, so it is parsed and
    re-emitted; everything else passes through untouched.
    """
    if not isinstance(document, dict) or document.get("kind") != "ConfigMap":
        return document
    data = document.get("data")
    if not isinstance(data, dict) or _REALM_FILE not in data:
        return document
    realm = yaml.safe_load(data[_REALM_FILE])
    if not isinstance(realm, dict):
        return document
    kept = {k: v for k, v in realm.items() if k not in TEAM_OWNED_REALM_KEYS}
    return {**document, "data": {**data, _REALM_FILE: kept}}


def _documents(text: str) -> list[Any]:
    return [_strip_team_owned(d) for d in yaml.safe_load_all(text) if d]


def grant_drift(
    *,
    app: str,
    grant: str,
    rendered: str | None,
    team_files: Mapping[str, str],
) -> GrantDrift:
    """Compare one rendered grant's template-owned declarations against the branch.

    ``rendered`` is the grant's canonical render, or None when the install holds
    no such grant for this app. ``team_files`` maps a concern filename
    (``config.yaml``, ``jobs.yaml``, ...) to its text on the branch; a filename
    the folder does not carry may be omitted rather than passed empty.

    A concern file legally carries documents this grant did not write - the other
    capability's grant, most often - so the question is whether each rendered
    document is PRESENT, not whether the file equals the render.
    """
    if rendered is None or not rendered.strip():
        return GrantDrift(app=app, grant=grant, absent=True, drifted=())

    drifted: list[str] = []
    for filename, document in split_by_concern(rendered):
        expected = _strip_team_owned(yaml.safe_load(document))
        if expected is None:
            continue
        try:
            on_branch = _documents(team_files.get(filename, ""))
        except yaml.YAMLError:
            # An unparseable concern file is a difference worth reporting rather
            # than an exception to raise: the caller wants a verdict, and a file
            # that does not parse certainly does not match the template.
            drifted.append(filename)
            continue
        if expected not in on_branch:
            drifted.append(filename)

    return GrantDrift(
        app=app,
        grant=grant,
        absent=False,
        drifted=tuple(sorted(set(drifted))),
    )
