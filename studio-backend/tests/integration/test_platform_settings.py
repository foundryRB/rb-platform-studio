"""Platform settings: the curated read, and the conformance-gated write.

Issue #6's ask, end to end: a named set of platform knobs (the observability
retention horizons) rendered from the install's own values on its deploy
branch, and tuned by a gated pull request against that branch.

The knobs address `values.yaml` because that is the whole of what the studio's
checkout is. The deploy branch carries foundry.yaml, values.yaml, root/ and
teams/ - and no `k8s/` chart source at all, so a knob pointed at a chart
template reads null forever and writes a file the branch does not have. That is
exactly the bug this suite's first version encoded: it created the chart path
inside the synthetic checkout and asserted a value came back, which no real
install could ever reproduce. The deploy-branch shape is now the fixture's
shape, so the read is tested against the file the studio actually has.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pytest_intent import intent

from studio.domain.services.platform_settings import (
    CURATED_SETTINGS,
    VALUES_FILE,
    build_setting,
    find_setting,
    resolve_value,
    set_value,
    validation_error,
)
from tests.conftest import FakeGitPr

_LOG_RETENTION = "observability.log-retention"
_MAX_RUNNERS = "arc.max-runners"

# An install's values.yaml with the block already present, comments and all:
# the shape the writer has to leave intact everywhere it is not writing.
_WITH_BLOCK = """# How the test install is configured.
zone: lab.example.dev
operators:
  - operator@example.test

# Retention horizons.
observability:
  logRetention: 720h         # 30 days
  metricsRetention: 10d
"""


class TestResolveValue:
    def test_reads_a_nested_scalar(self) -> None:
        assert resolve_value(_WITH_BLOCK, ("observability", "logRetention")) == "720h"

    def test_an_unset_key_is_none(self) -> None:
        assert resolve_value(_WITH_BLOCK, ("observability", "tracesRetention")) is None

    def test_an_absent_block_is_none(self) -> None:
        assert resolve_value("zone: lab.example.dev\n", ("observability", "logRetention")) is None

    def test_an_absent_file_is_none(self) -> None:
        assert resolve_value(None, ("observability", "logRetention")) is None

    def test_a_mapping_has_no_scalar_to_render(self) -> None:
        assert resolve_value(_WITH_BLOCK, ("observability",)) is None

    def test_unparseable_values_read_as_unset(self) -> None:
        # Malformed YAML must not crash the read surface: the knob reports
        # unset, and the gate is what refuses the branch.
        assert resolve_value("zone: [unclosed\n", ("observability", "logRetention")) is None


class TestSetValue:
    def test_replaces_an_existing_value_in_place(self) -> None:
        out = set_value(_WITH_BLOCK, ("observability", "logRetention"), "168h")
        assert resolve_value(out, ("observability", "logRetention")) == "168h"
        # Everything else survives byte-for-byte.
        assert "# How the test install is configured." in out
        assert "zone: lab.example.dev" in out
        assert "  - operator@example.test" in out
        assert "# Retention horizons." in out
        assert "  metricsRetention: 10d" in out

    def test_drops_a_stale_inline_comment_on_the_line_it_rewrites(self) -> None:
        # "# 30 days" would be a lie next to 168h, and the studio cannot rewrite
        # it truthfully; the pull request shows the removal.
        out = set_value(_WITH_BLOCK, ("observability", "logRetention"), "168h")
        assert "logRetention: 168h" in out
        assert "30 days" not in out

    def test_adds_a_key_to_an_existing_block(self) -> None:
        out = set_value(_WITH_BLOCK, ("observability", "tracesRetention"), "24h")
        assert resolve_value(out, ("observability", "tracesRetention")) == "24h"
        # The siblings are untouched and the new key joins their block.
        assert resolve_value(out, ("observability", "logRetention")) == "720h"
        assert resolve_value(out, ("observability", "metricsRetention")) == "10d"
        assert "  tracesRetention: 24h" in out

    def test_creates_the_block_when_the_install_has_none(self) -> None:
        text = "zone: lab.example.dev\noperators:\n  - operator@example.test\n"
        out = set_value(text, ("observability", "logRetention"), "168h")
        assert resolve_value(out, ("observability", "logRetention")) == "168h"
        assert resolve_value(out, ("zone",)) == "lab.example.dev"
        assert out.endswith("\n")
        assert "\n\n\n" not in out

    def test_keeps_the_file_valid_yaml_and_singly_newline_terminated(self) -> None:
        out = set_value(_WITH_BLOCK, ("observability", "logRetention"), "168h")
        assert out.endswith("\n")
        assert not out.endswith("\n\n")

    def test_preserves_crlf_line_endings(self) -> None:
        out = set_value(_WITH_BLOCK.replace("\n", "\r\n"), ("observability", "logRetention"), "1h")
        assert "\r\n" in out
        assert "\n" not in out.replace("\r\n", "")
        assert resolve_value(out, ("observability", "logRetention")) == "1h"

    def test_a_rewrite_is_idempotent(self) -> None:
        once = set_value(_WITH_BLOCK, ("observability", "tracesRetention"), "24h")
        twice = set_value(once, ("observability", "tracesRetention"), "24h")
        assert once == twice

    def test_adopts_the_files_own_indentation(self) -> None:
        text = "observability:\n    logRetention: 720h\n"
        out = set_value(text, ("observability", "tracesRetention"), "24h")
        assert "    tracesRetention: 24h" in out
        assert resolve_value(out, ("observability", "tracesRetention")) == "24h"


class TestValidation:
    @pytest.mark.parametrize("value", ["0", "2", "8", "100"])
    def test_a_non_negative_runner_count_is_admitted(self, value: str) -> None:
        assert validation_error(find_setting(_MAX_RUNNERS), value) is None

    @pytest.mark.parametrize("value", ["", "-1", "1.5", "2 runners", "01", "unlimited"])
    def test_a_non_integer_runner_count_is_refused(self, value: str) -> None:
        assert validation_error(find_setting(_MAX_RUNNERS), value) is not None

    @pytest.mark.parametrize("value", ["720h", "30d", "1w", "500ms", "10y"])
    def test_a_well_formed_duration_is_admitted(self, value: str) -> None:
        assert validation_error(find_setting(_LOG_RETENTION), value) is None

    @pytest.mark.parametrize("value", ["", "  ", "720", "-1h", "0h", "soon", "30 d", "h"])
    def test_a_malformed_duration_is_refused(self, value: str) -> None:
        # Refused here rather than by the gate: the suite has no opinion on a
        # values string, so a bad duration would merge clean and only surface as
        # a component that will not start at the next sync.
        assert validation_error(find_setting(_LOG_RETENTION), value) is not None


class TestRegistry:
    @intent("INT-SETTINGS-001")
    def test_every_knob_declares_a_default_and_a_values_path(self) -> None:
        """INT-SETTINGS-001: every curated knob names a values path and a chart
        default, and that default itself satisfies the knob's unit."""
        for curated in CURATED_SETTINGS:
            assert curated.default.strip(), f"{curated.key} has no chart default"
            assert len(curated.path) >= 1, f"{curated.key} has no values path"
            assert validation_error(curated, curated.default) is None, (
                f"{curated.key}'s own default does not satisfy its unit"
            )

    def test_keys_are_unique(self) -> None:
        keys = [curated.key for curated in CURATED_SETTINGS]
        assert len(keys) == len(set(keys))

    def test_build_setting_separates_the_pinned_value_from_the_default(self) -> None:
        curated = find_setting(_LOG_RETENTION)
        unset = build_setting(curated, "zone: lab.example.dev\n")
        assert unset.value is None
        assert unset.effective == curated.default

        pinned = build_setting(curated, _WITH_BLOCK)
        assert pinned.value == "720h"
        assert pinned.effective == "720h"


class TestSettingsRead:
    def test_unpinned_runner_ceiling_uses_chart_default(self, client: TestClient) -> None:
        knob = next(s for s in client.get("/api/settings").json() if s["key"] == _MAX_RUNNERS)
        assert knob["value"] is None
        assert knob["effective"] == "8"
        assert knob["field"] == "arc.maxRunners"
        assert knob["unit"] == "count"

    @intent("INT-SETTINGS-001")
    def test_an_install_that_pins_nothing_reports_the_chart_default(
        self, client: TestClient
    ) -> None:
        """INT-SETTINGS-001: the knob addresses the install's own values.yaml,
        and an unpinned knob reports value null with the chart default beside
        it rather than conflating the two."""
        res = client.get("/api/settings")
        assert res.status_code == 200
        knob = next(s for s in res.json() if s["key"] == _LOG_RETENTION)
        assert knob["value"] is None
        assert knob["default"] == "720h"
        assert knob["effective"] == "720h"
        assert knob["source"] == VALUES_FILE
        assert knob["field"] == "observability.logRetention"
        assert knob["category"] == "observability"
        assert knob["unit"] == "duration"

    def test_reads_what_the_deploy_branch_pins(
        self, client: TestClient, platform_root: Path
    ) -> None:
        (platform_root / VALUES_FILE).write_text(_WITH_BLOCK, encoding="utf-8")
        res = client.get("/api/settings")
        knobs = {s["key"]: s for s in res.json()}
        assert knobs[_LOG_RETENTION]["value"] == "720h"
        assert knobs["observability.metrics-retention"]["value"] == "10d"
        # Pinned nothing: still the chart's own default.
        assert knobs["observability.traces-retention"]["value"] is None
        assert knobs["observability.traces-retention"]["effective"] == "72h"

    def test_the_whole_registry_is_rendered(self, client: TestClient) -> None:
        keys = {s["key"] for s in client.get("/api/settings").json()}
        assert keys == {curated.key for curated in CURATED_SETTINGS}


class TestSettingsWrite:
    def test_runner_ceiling_zero_is_saved_and_read_back(
        self, client: TestClient, platform_root: Path, fake_git: FakeGitPr
    ) -> None:
        before = (platform_root / VALUES_FILE).read_text(encoding="utf-8")
        res = client.put(f"/api/settings/{_MAX_RUNNERS}", json={"value": "0"})
        assert res.status_code == 200, res.text
        assert res.json()["changed_files"] == [VALUES_FILE]
        assert fake_git.prepared == ["settings/arc-max-runners"]

        after = (platform_root / VALUES_FILE).read_text(encoding="utf-8")
        assert resolve_value(after, ("arc", "maxRunners")) == "0"
        assert after.startswith(before)
        knob = next(s for s in client.get("/api/settings").json() if s["key"] == _MAX_RUNNERS)
        assert knob["value"] == "0"
        assert knob["effective"] == "0"
        assert "runner capacity" in fake_git.finalized[-1]["pr_body"]

    def test_malformed_runner_ceiling_writes_nothing(
        self, client: TestClient, platform_root: Path, fake_git: FakeGitPr
    ) -> None:
        before = (platform_root / VALUES_FILE).read_text(encoding="utf-8")
        res = client.put(f"/api/settings/{_MAX_RUNNERS}", json={"value": "1.5"})
        assert res.status_code == 400
        assert (platform_root / VALUES_FILE).read_text(encoding="utf-8") == before
        assert fake_git.prepared == []

    def test_tuning_a_knob_ships_as_a_pull_request(
        self, client: TestClient, platform_root: Path, fake_git: FakeGitPr
    ) -> None:
        res = client.put(f"/api/settings/{_LOG_RETENTION}", json={"value": "168h"})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["changed_files"] == [VALUES_FILE]
        assert body["pr"]["number"] == 7
        assert body["branch"] == "settings/observability-log-retention"
        # The value landed on the branch, and the read surface now reports it.
        assert resolve_value(
            (platform_root / VALUES_FILE).read_text(encoding="utf-8"),
            ("observability", "logRetention"),
        ) == "168h"
        knob = next(s for s in client.get("/api/settings").json() if s["key"] == _LOG_RETENTION)
        assert knob["value"] == "168h"
        assert fake_git.prepared == ["settings/observability-log-retention"]

    def test_the_pull_request_records_the_move_and_that_no_pin_moves(
        self, client: TestClient, fake_git: FakeGitPr
    ) -> None:
        client.put(f"/api/settings/{_LOG_RETENTION}", json={"value": "168h"})
        pr = fake_git.finalized[-1]
        assert "168h" in pr["pr_title"]
        assert "observability.logRetention" in pr["pr_body"]
        # It says where the value came from (the chart default, unpinned here)...
        assert "chart default" in pr["pr_body"]
        # ...and that activating it needs no chart pin bump.
        assert "no chart pin moves" in pr["pr_body"]
        assert VALUES_FILE in pr["pr_body"]
        assert pr["commit_message"].startswith("chore(settings):")

    def test_an_unknown_key_is_404(self, client: TestClient) -> None:
        res = client.put("/api/settings/observability.nope", json={"value": "1h"})
        assert res.status_code == 404

    @intent("INT-SETTINGS-001")
    def test_a_malformed_value_is_400_and_writes_nothing(
        self, client: TestClient, platform_root: Path, fake_git: FakeGitPr
    ) -> None:
        """INT-SETTINGS-001: a value the knob's unit does not admit is refused
        before any branch is prepared - the gate has no opinion on a values
        string, so it would merge clean and break the component at sync."""
        before = (platform_root / VALUES_FILE).read_text(encoding="utf-8")
        res = client.put(f"/api/settings/{_LOG_RETENTION}", json={"value": "forever"})
        assert res.status_code == 400
        assert (platform_root / VALUES_FILE).read_text(encoding="utf-8") == before
        # Refused before the gate: no branch was even prepared.
        assert fake_git.prepared == []

    @intent("INT-SETTINGS-001")
    def test_setting_a_knob_to_the_value_it_already_has_is_refused(
        self, client: TestClient, platform_root: Path, fake_git: FakeGitPr
    ) -> None:
        """INT-SETTINGS-001: a no-op is refused before a branch is prepared,
        rather than opening an empty pull request against the deploy branch."""
        (platform_root / VALUES_FILE).write_text(_WITH_BLOCK, encoding="utf-8")
        res = client.put(f"/api/settings/{_LOG_RETENTION}", json={"value": "720h"})
        assert res.status_code == 409
        assert fake_git.prepared == []

    def test_pinning_the_chart_default_explicitly_is_allowed(
        self, client: TestClient, platform_root: Path
    ) -> None:
        # The install pins nothing, so the effective value is already 720h - but
        # pinning it is a real change: it survives a chart whose default moves.
        res = client.put(f"/api/settings/{_LOG_RETENTION}", json={"value": "720h"})
        assert res.status_code == 200
        assert resolve_value(
            (platform_root / VALUES_FILE).read_text(encoding="utf-8"),
            ("observability", "logRetention"),
        ) == "720h"

    @intent("INT-SETTINGS-001")
    def test_a_failed_gate_rolls_the_values_file_back_byte_identical(
        self, failing_client: TestClient, platform_root: Path, fake_git: FakeGitPr
    ) -> None:
        """INT-SETTINGS-001: a rejected settings change leaves values.yaml
        byte-identical and opens no pull request."""
        before = (platform_root / VALUES_FILE).read_text(encoding="utf-8")
        res = failing_client.put(f"/api/settings/{_LOG_RETENTION}", json={"value": "168h"})
        assert res.status_code == 422
        assert (platform_root / VALUES_FILE).read_text(encoding="utf-8") == before
        assert fake_git.aborted == ["settings/observability-log-retention"]
        assert fake_git.finalized == []

    def test_the_local_composition_leaves_the_change_in_the_working_tree(
        self, local_client: TestClient, platform_root: Path
    ) -> None:
        res = local_client.put(f"/api/settings/{_LOG_RETENTION}", json={"value": "168h"})
        assert res.status_code == 200
        assert res.json()["pr"] is None
        assert resolve_value(
            (platform_root / VALUES_FILE).read_text(encoding="utf-8"),
            ("observability", "logRetention"),
        ) == "168h"

    def test_writing_one_knob_leaves_the_others_alone(
        self, client: TestClient, platform_root: Path
    ) -> None:
        (platform_root / VALUES_FILE).write_text(_WITH_BLOCK, encoding="utf-8")
        client.put("/api/settings/observability.traces-retention", json={"value": "24h"})
        knobs = {s["key"]: s for s in client.get("/api/settings").json()}
        assert knobs["observability.traces-retention"]["value"] == "24h"
        assert knobs[_LOG_RETENTION]["value"] == "720h"
        assert knobs["observability.metrics-retention"]["value"] == "10d"
        # The install's unrelated configuration is untouched.
        text = (platform_root / VALUES_FILE).read_text(encoding="utf-8")
        assert resolve_value(text, ("zone",)) == "lab.example.dev"
        assert "# How the test install is configured." in text
