"""INT-EVENTS-001: publishing is one-way. With the bus unreachable, every act that
would publish completes with the same outcome, the same response, and the same
durable state as it does with the bus up, and each dropped publish is logged."""

from __future__ import annotations

import json
import logging
import shutil
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pytest_intent import intent

from studio.adapters.inbound.http.app import create_app
from studio.adapters.outbound.events.cloudevent import SOURCE, envelope
from studio.application.services.event_types import (
    APP_OFFBOARDED,
    APP_ONBOARDED,
    APP_PAUSED,
    APP_RESUMED,
    CHANGE_OPENED,
    CONFORMANCE_COMPLETED,
    GRANT_ISSUED,
    PROMOTION_FROZEN,
    PROMOTION_RESUMED,
    SETTING_CHANGED,
    pr_pointer,
    state_fact,
)
from studio.domain.model.pr_info import PrInfo
from tests.conftest import FakeGitPr, StubConformance, build_container


@contextmanager
def captured_warnings():
    """Collect the studio's own warnings.

    The studio configures its logger namespace with propagate off, so records
    never reach pytest's root-level caplog handler; a handler on that namespace
    is how a test sees them.
    """
    records: list[logging.LogRecord] = []

    class Sink(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    sink = Sink(level=logging.WARNING)
    logger = logging.getLogger("studio")
    logger.addHandler(sink)
    try:
        yield records
    finally:
        logger.removeHandler(sink)


class RaisingPublisher:
    """A bus that is down in the least forgiving way: every publish explodes."""

    def __init__(self) -> None:
        self.attempts: list[str] = []

    def publish(self, *, event_type: str, subject: str, data: dict[str, object]) -> None:
        self.attempts.append(event_type)
        raise ConnectionError("bus unreachable")


class RecordingPublisher:
    """A bus that is up, so the two runs can be compared.

    It builds the real envelope before recording, so a ``data`` the adapter
    could not serialize fails here rather than being dropped in production:
    the first publisher handed a ``PrInfo`` dataclass to ``data``, the JSON
    encoder refused it inside the NATS adapter, and every onboarding that
    opened a pull request published nothing while this fake recorded a hit.
    """

    def __init__(self) -> None:
        self.published: list[tuple[str, str, dict[str, object]]] = []

    def publish(self, *, event_type: str, subject: str, data: dict[str, object]) -> None:
        envelope(event_type=event_type, subject=subject, data=data)
        self.published.append((event_type, subject, data))


def _onboard(client: TestClient) -> tuple[int, dict]:
    response = client.post(
        "/api/onboard/app",
        json={
            "name": "eventful",
            "display_name": "Eventful",
            "description": "An app that says what happened",
            "icon": "mdi-bell",
            "image_components": ["server", "docs"],
        },
    )
    return response.status_code, response.json()


@intent("INT-EVENTS-001")
def test_onboarding_is_identical_with_the_bus_down(
    platform_root: Path, tmp_path: Path
) -> None:
    """The act that would publish completes the same, up or down.

    Two independent installs, so the comparison is of the act itself and not of
    a fake's incrementing pull-request number.
    """
    root_up = tmp_path / "up"
    root_down = tmp_path / "down"
    shutil.copytree(platform_root, root_up)
    shutil.copytree(platform_root, root_down)

    up = RecordingPublisher()
    container = build_container(root_up, StubConformance(), FakeGitPr(), events=up)
    status_up, body_up = _onboard(TestClient(create_app(container)))
    assert status_up == 200, body_up
    assert [e[0] for e in up.published] == [CHANGE_OPENED, APP_ONBOARDED]
    # The pull request rides as its URL, the pointer a consumer fetches from.
    assert up.published[-1][2]["pr"] == "https://github.example/test/pulls/7"

    # Same install, same request, but the bus raises on every publish.
    down = RaisingPublisher()
    container = build_container(root_down, StubConformance(), FakeGitPr(), events=down)
    with captured_warnings() as warnings:
        status_down, body_down = _onboard(TestClient(create_app(container)))

    assert down.attempts == [CHANGE_OPENED, APP_ONBOARDED], "the act must still publish"
    # Identical outcome and identical response.
    assert status_down == status_up
    assert body_down == body_up
    # And the drop is visible rather than silent.
    assert any(APP_ONBOARDED in record.getMessage() for record in warnings), (
        "a dropped publish must be logged at warning"
    )


@intent("INT-EVENTS-001")
def test_conformance_run_is_identical_with_the_bus_down(
    platform_root: Path, fake_git: FakeGitPr
) -> None:
    up = RecordingPublisher()
    container = build_container(platform_root, StubConformance(), fake_git, events=up)
    report_up = container.run_conformance().execute()
    assert [e[0] for e in up.published] == [CONFORMANCE_COMPLETED]

    down = RaisingPublisher()
    container = build_container(platform_root, StubConformance(), fake_git, events=down)
    with captured_warnings() as warnings:
        report_down = container.run_conformance().execute()

    assert down.attempts == [CONFORMANCE_COMPLETED]
    assert report_down == report_up
    assert any(CONFORMANCE_COMPLETED in record.getMessage() for record in warnings)


def _post(path: str, payload: dict | None = None) -> Callable[[TestClient], tuple[int, dict]]:
    def drive(client: TestClient) -> tuple[int, dict]:
        response = client.post(path, json=payload) if payload is not None else client.post(path)
        return response.status_code, response.json()

    return drive


def _put(path: str, payload: dict) -> Callable[[TestClient], tuple[int, dict]]:
    def drive(client: TestClient) -> tuple[int, dict]:
        response = client.put(path, json=payload)
        return response.status_code, response.json()

    return drive


def _then(first: str, second: str) -> Callable[[TestClient], tuple[int, dict]]:
    """Two toggles in a row; the second is the act under test."""

    def drive(client: TestClient) -> tuple[int, dict]:
        assert client.post(first).status_code == 200
        response = client.post(second)
        return response.status_code, response.json()

    return drive


# Every act the studio performs that changes what an install runs, the request
# that drives it, and the facts it states in order. The gated acts state
# change.opened first (the pull request is the one fact every gated act
# shares) and their own fact second.
_ACTS = [
    pytest.param(
        _post("/api/offboard/app", {"name": "beta-app"}),
        [CHANGE_OPENED, APP_OFFBOARDED],
        id="offboard",
    ),
    pytest.param(
        _post("/api/onboard/database", {"name": "alpha-app"}),
        [CHANGE_OPENED, GRANT_ISSUED],
        id="grant-database",
    ),
    pytest.param(
        _post("/api/onboard/identity", {"name": "alpha-app"}),
        [CHANGE_OPENED, GRANT_ISSUED],
        id="grant-identity",
    ),
    pytest.param(
        _post("/api/onboard/events", {"name": "alpha-app", "domains": ["alpha"]}),
        [CHANGE_OPENED, GRANT_ISSUED],
        id="grant-events",
    ),
    pytest.param(
        _put("/api/settings/observability.log-retention", {"value": "168h"}),
        [CHANGE_OPENED, SETTING_CHANGED],
        id="setting",
    ),
    pytest.param(_post("/api/apps/alpha-app/pause"), [APP_PAUSED], id="pause"),
    pytest.param(
        _then("/api/apps/alpha-app/pause", "/api/apps/alpha-app/resume"),
        [APP_PAUSED, APP_RESUMED],
        id="resume",
    ),
    pytest.param(
        _post("/api/apps/alpha-app/promotion/freeze"), [PROMOTION_FROZEN], id="freeze"
    ),
    pytest.param(
        _then("/api/apps/alpha-app/promotion/freeze", "/api/apps/alpha-app/promotion/resume"),
        [PROMOTION_FROZEN, PROMOTION_RESUMED],
        id="resume-promotion",
    ),
]


@intent("INT-EVENTS-001")
@pytest.mark.parametrize(("drive", "facts"), _ACTS)
def test_every_act_is_identical_with_the_bus_down(
    platform_root: Path,
    tmp_path: Path,
    drive: Callable[[TestClient], tuple[int, dict]],
    facts: list[str],
) -> None:
    """Each act states its facts with the bus up, attempts the same facts with
    the bus down, and completes with the same status and the same response
    either way; every drop is logged. Two install copies, so the comparison is
    of the act and not of the fake's incrementing pull-request number."""
    root_up = tmp_path / "up"
    root_down = tmp_path / "down"
    shutil.copytree(platform_root, root_up)
    shutil.copytree(platform_root, root_down)

    up = RecordingPublisher()
    container = build_container(root_up, StubConformance(), FakeGitPr(), events=up)
    status_up, body_up = drive(TestClient(create_app(container)))
    assert status_up == 200, body_up
    assert [e[0] for e in up.published] == facts
    for event_type, subject, data in up.published:
        assert subject, event_type
        # Pointers, never records: the pull request is a URL or absent.
        if "pr" in data:
            assert data["pr"] is None or str(data["pr"]).startswith("https://")

    down = RaisingPublisher()
    container = build_container(root_down, StubConformance(), FakeGitPr(), events=down)
    with captured_warnings() as warnings:
        status_down, body_down = drive(TestClient(create_app(container)))

    assert down.attempts == facts, "the act must still attempt each publish"
    assert status_down == status_up
    assert body_down == body_up
    for fact in facts:
        assert any(fact in record.getMessage() for record in warnings), (
            f"a dropped {fact} must be logged at warning"
        )


@intent("INT-EVENTS-001")
def test_an_idempotent_toggle_states_nothing(platform_root: Path) -> None:
    """Pausing a paused app changes nothing on the branch, so no fact is
    stated: an event is a past-tense statement of something that happened."""
    up = RecordingPublisher()
    container = build_container(platform_root, StubConformance(), FakeGitPr(), events=up)
    client = TestClient(create_app(container))
    assert client.post("/api/apps/alpha-app/pause").status_code == 200
    assert client.post("/api/apps/alpha-app/pause").status_code == 200
    assert [e[0] for e in up.published] == [APP_PAUSED]


@intent("INT-EVENTS-001")
def test_the_pull_request_pointer_is_its_url() -> None:
    """A PrInfo is a dataclass the JSON envelope cannot carry; the pointer the
    event carries is the URL, and an absent pull request is None."""
    pr = PrInfo(
        number=7,
        title="t",
        url="https://github.example/test/pulls/7",
        branch="b",
        state="open",
        merged=False,
    )
    assert pr_pointer(pr) == "https://github.example/test/pulls/7"
    assert pr_pointer(None) is None
    envelope(event_type=APP_ONBOARDED, subject="x", data={"pr": pr_pointer(pr)})
    with pytest.raises(TypeError):
        envelope(event_type=APP_ONBOARDED, subject="x", data={"pr": pr})


_EVENTS_PAGE = Path(__file__).resolve().parents[3] / "docs/src/content/docs/reference/events.md"


@intent("INT-EVENTS-001")
def test_the_events_page_states_exactly_the_types_the_publisher_emits() -> None:
    """REF-Events section 3: each owner states its own types on its own page,
    held against the publisher by its own tests. The page is the consumer's
    contract; the constants are what the adapter emits; neither moves alone."""
    import re

    import studio.application.services.event_types as types

    emitted = {
        value
        for name, value in vars(types).items()
        if name.isupper() and isinstance(value, str) and value.startswith("com.foundry.")
    }
    assert emitted, "the publisher declares no types"
    assert all(value.startswith("com.foundry.platform.") for value in emitted), (
        "every type is under the one domain this studio owns"
    )
    page = _EVENTS_PAGE.read_text(encoding="utf-8")
    stated = set(re.findall(r"^\| `(com\.foundry\.[a-z.]+)` \|", page, flags=re.M))
    assert stated == emitted, (
        f"page states {sorted(stated - emitted)} the publisher never emits; "
        f"publisher emits {sorted(emitted - stated)} the page never states"
    )


@intent("INT-EVENTS-001")
def test_state_fact_never_raises() -> None:
    """The guarantee is made true at the call site, not assumed of the adapter."""
    with captured_warnings() as warnings:
        state_fact(
            RaisingPublisher(),
            event_type=APP_ONBOARDED,
            subject="anything",
            data={},
        )
    assert warnings, "the drop must be logged"


@intent("INT-EVENTS-001")
def test_the_envelope_is_a_cloudevent_carrying_pointers_not_payloads() -> None:
    """REF-Events sections 2 and 5: the required attributes, and no record body."""
    raw = envelope(
        event_type=APP_ONBOARDED,
        subject="eventful",
        data={"app": "eventful", "branch": "onboard/eventful", "pr": None},
    )
    event = json.loads(raw)

    assert event["specversion"] == "1.0"
    assert event["type"] == APP_ONBOARDED
    assert event["subject"] == "eventful"
    assert event["source"] == SOURCE
    assert event["datacontenttype"] == "application/json"
    assert event["id"] and event["time"]

    # `id` is the consumer's dedupe key, so two events are never the same event.
    other = json.loads(envelope(event_type=APP_ONBOARDED, subject="eventful", data={}))
    assert other["id"] != event["id"]

    # The type is one registered row, never composed at the call site.
    assert APP_ONBOARDED.startswith("com.foundry.platform.")
    assert CONFORMANCE_COMPLETED.startswith("com.foundry.platform.")
