"""INT-GRANT-007: a grant's rendered form against the bytes on the install's branch.

The gap this closes is that a frozen grant is not wrong against any check that
exists, so a template change reaches existing grants only as a hand sweep and
nothing reports the ones it missed.
"""

from __future__ import annotations

import pytest
from pytest_intent import intent

from studio.domain.model.default_broker import DefaultBroker
from studio.domain.services.grant_drift import grant_drift
from studio.domain.services.identity_grant import render_identity_blocks
from studio.domain.services.team_documents import split_by_concern

# Drift is render-against-branch, so any declaration works as long as both sides
# use it; the install's own is what the real read passes in.
_BROKERS = (DefaultBroker("google", "google", "keycloak-google"),)

_APP = "scrapyard"
_HOST = "scrapyard.example.com"

_OTHER_GRANT_DOC = (
    "apiVersion: batch/v1\nkind: Job\nmetadata:\n  name: gen-pg-app-scrapyard\n---\n"
)
_STALE_FIELD = "webOrigins:\n          - https://x\n"
_HAND_ADDED_URI = "          - https://scrapyard.example.com/w/oauth2/callback\n"


def _team_files_from(rendered: str) -> dict[str, str]:
    """The team folder an install would carry for a freshly rendered grant."""
    files: dict[str, str] = {}
    for filename, document in split_by_concern(rendered):
        prior = files.get(filename)
        files[filename] = f"{prior}\n---\n{document}\n" if prior else f"{document}\n"
    return files


@intent("INT-GRANT-007")
def test_a_freshly_rendered_grant_reports_in_sync() -> None:
    rendered = render_identity_blocks(_APP, _HOST, _BROKERS)
    result = grant_drift(
        app=_APP,
        grant="identity",
        rendered=rendered,
        team_files=_team_files_from(rendered),
    )
    assert result.in_sync
    assert result.drifted == ()
    assert not result.absent


@intent("INT-GRANT-007")
def test_a_grant_the_install_does_not_hold_reports_absent_not_drifted() -> None:
    """An app with no realm must not read as a difference, or every app without
    a capability looks broken."""
    result = grant_drift(app=_APP, grant="identity", rendered=None, team_files={})
    assert result.absent
    assert result.drifted == ()
    assert not result.in_sync


@intent("INT-GRANT-007")
def test_a_concern_file_carrying_other_grants_documents_is_not_drift() -> None:
    """Files are shared: the database grant's documents sit beside the identity
    grant's. The question is presence of each rendered document, not equality."""
    rendered = render_identity_blocks(_APP, _HOST, _BROKERS)
    files = _team_files_from(rendered)
    files["jobs.yaml"] = _OTHER_GRANT_DOC + files["jobs.yaml"]
    result = grant_drift(
        app=_APP, grant="identity", rendered=rendered, team_files=files
    )
    assert result.in_sync, result.summary()


@intent("INT-GRANT-007")
@pytest.mark.parametrize(
    "injected",
    [
        pytest.param(_STALE_FIELD, id="a-field-the-template-stopped-rendering"),
        pytest.param(_HAND_ADDED_URI, id="a-hand-added-redirect-uri"),
    ],
)
def test_a_hand_edited_grant_file_is_reported(injected: str) -> None:
    """The two real defects this exists for: a stale field the template no longer
    renders (#123), and a URI hand-added to one install's client (#140)."""
    rendered = render_identity_blocks(_APP, _HOST, _BROKERS)
    files = _team_files_from(rendered)
    lines = files["config.yaml"].splitlines(keepends=True)
    cut = next(i for i, line in enumerate(lines) if "redirectUris:" in line)
    files["config.yaml"] = "".join(lines[: cut + 2] + [injected] + lines[cut + 2 :])
    result = grant_drift(
        app=_APP, grant="identity", rendered=rendered, team_files=files
    )
    assert not result.in_sync
    assert "config.yaml" in result.drifted
    assert "no longer matches the canonical template" in result.summary()


@intent("INT-GRANT-007")
def test_admitting_a_person_to_the_realm_is_not_drift() -> None:
    """THE regression this check must never lose. A realm's users list IS its
    access allowlist: people are admitted by hand, by design, and a render keyed
    on the app name cannot know them. Reporting an admitted user as drift invites
    a "repair" that deletes the person, and normalising the fleet against the
    template proposed exactly that on two live realms before a semantic guard
    stopped it."""
    rendered = render_identity_blocks(_APP, _HOST, _BROKERS)
    files = _team_files_from(rendered)
    files["config.yaml"] = files["config.yaml"].replace(
        f"      - username: {_APP}-admin\n",
        "      - username: someone\n"
        "        email: someone@example.test\n"
        "        enabled: true\n"
        "        emailVerified: true\n"
        f"      - username: {_APP}-admin\n",
        1,
    )
    result = grant_drift(
        app=_APP, grant="identity", rendered=rendered, team_files=files
    )
    assert result.in_sync, result.summary()


@intent("INT-GRANT-007")
def test_a_comment_change_is_not_drift() -> None:
    """Comments are not meaning. A grant whose declarations are identical but
    whose comment block predates a template edit is not drifted in any sense
    worth reporting, and reporting it makes the check noise on first contact."""
    rendered = render_identity_blocks(_APP, _HOST, _BROKERS)
    files = _team_files_from(rendered)
    files["config.yaml"] = "# a comment the template does not render\n" + files["config.yaml"]
    result = grant_drift(
        app=_APP, grant="identity", rendered=rendered, team_files=files
    )
    assert result.in_sync, result.summary()


@intent("INT-GRANT-007")
def test_crlf_alone_is_not_drift() -> None:
    """The branch is read over git on whatever checked it out; calling a line
    ending a difference would report every app on a Windows-authored branch."""
    rendered = render_identity_blocks(_APP, _HOST, _BROKERS)
    files = {k: v.replace("\n", "\r\n") for k, v in _team_files_from(rendered).items()}
    result = grant_drift(
        app=_APP, grant="identity", rendered=rendered, team_files=files
    )
    assert result.in_sync, result.summary()


@intent("INT-GRANT-007")
def test_the_report_never_rewrites_the_branch() -> None:
    """It is a read. Reconcile writes the files it owns wholesale, which is how
    reconciling solveos deleted a live generator's RBAC (#100); the same write
    aimed at grant files, which share concern files, repeats that with more to
    lose. The team_files mapping must come back untouched."""
    rendered = render_identity_blocks(_APP, _HOST, _BROKERS)
    files = _team_files_from(rendered)
    before = dict(files)
    grant_drift(app=_APP, grant="identity", rendered=rendered, team_files=files)
    assert files == before
