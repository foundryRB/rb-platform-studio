"""The install's environment declaration: what the manifest says an install runs,
and which of those the platform deploys into automatically."""

import pytest

from studio.domain.services.environments import (
    LEGACY_ENVIRONMENTS,
    declared_environments,
    entry_environment,
)


class TestDeclaredEnvironments:
    def test_a_manifest_declaring_nothing_keeps_the_legacy_layout(self) -> None:
        # Branches authored before the field existed must read unchanged.
        assert declared_environments({"install": "example"}) == LEGACY_ENVIRONMENTS

    def test_names_are_read_in_declaration_order(self) -> None:
        assert declared_environments({"environments": ["prod", "staging"]}) == (
            "prod",
            "staging",
        )

    def test_an_entry_may_be_a_map_carrying_the_name(self) -> None:
        # The list can grow per-environment fields later without reshaping.
        assert declared_environments(
            {"environments": [{"name": "prod"}, {"name": "uat"}]}
        ) == ("prod", "uat")

    def test_an_empty_declaration_is_refused(self) -> None:
        # An install runs at least one environment; an empty list is a hand's
        # mistake, and deploying against it would deploy nowhere.
        with pytest.raises(ValueError, match="non-empty list"):
            declared_environments({"environments": []})

    def test_a_non_list_declaration_is_refused(self) -> None:
        with pytest.raises(ValueError, match="non-empty list"):
            declared_environments({"environments": "prod"})

    def test_a_name_that_is_not_a_label_is_refused(self) -> None:
        with pytest.raises(ValueError, match="does not name an environment"):
            declared_environments({"environments": ["Prod Live"]})

    def test_a_duplicate_environment_is_refused(self) -> None:
        with pytest.raises(ValueError, match="declared twice"):
            declared_environments({"environments": ["prod", "prod"]})

    def test_a_malformed_declaration_never_falls_back_silently(self) -> None:
        # Falling back would deploy against a layout the hand did not declare,
        # which is the whole failure the loudness prevents.
        for bad in ({"environments": [{}]}, {"environments": [None]}):
            with pytest.raises(ValueError):
                declared_environments(bad)


class TestEntryEnvironment:
    def test_the_first_declared_environment_is_the_entry(self) -> None:
        assert entry_environment(("prod", "staging")) == "prod"
        assert entry_environment(declared_environments({})) == "dev"

    def test_no_environment_at_all_is_refused(self) -> None:
        with pytest.raises(ValueError, match="at least one environment"):
            entry_environment(())
