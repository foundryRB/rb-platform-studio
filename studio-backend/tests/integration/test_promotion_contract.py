"""The promotion contract: the scaffold declares nothing, the parse is loud."""

import pytest

from studio.domain.services.app_repo_scaffold import render_app_repo_scaffold
from studio.domain.services.promotion_contract import (
    CONTRACT_PATH,
    parse_promotion_contract,
    render_promotion_contract,
)


class TestScaffold:
    def test_the_scaffold_declares_no_target(self) -> None:
        # A new app promotes nowhere until a hand declares a destination; the
        # shape travels as comments in the file it will be declared in.
        assert parse_promotion_contract(render_promotion_contract()) == ()

    def test_the_app_repo_scaffold_ships_the_contract(self) -> None:
        files = render_app_repo_scaffold(
            app="gamma",
            display_name="Gamma",
            description="A test app",
            registry="ghcr.io/test-org",
        )
        assert files[CONTRACT_PATH] == render_promotion_contract()


class TestParse:
    def test_an_environment_target_carries_every_definition(self) -> None:
        (target,) = parse_promotion_contract(
            """
targets:
  - name: example-prod
    kind: environment
    install: example
    environment: prod
"""
        )
        assert (target.door, target.terms, target.acceptance) == (
            "commit",
            "version",
            "none",
        )
        assert (target.install, target.environment) == ("example", "prod")

    def test_a_repository_target_names_its_pair(self) -> None:
        (target,) = parse_promotion_contract(
            """
targets:
  - name: partner
    kind: repository
    repo: their-org/their-repo
    branch: main
    credential: partner-pair
    acceptance:
      probe: https://their-hostname.example
"""
        )
        assert (target.door, target.terms, target.acceptance) == (
            "pull-request",
            "source",
            "probe",
        )
        assert target.probe_url == "https://their-hostname.example"

    def test_a_repository_target_without_a_credential_name_is_refused(self) -> None:
        # Coordinates only ever live here; the credential is a NAME the
        # platform resolves, and a pair without one cannot act at all.
        with pytest.raises(ValueError, match="repo, branch and credential"):
            parse_promotion_contract(
                """
targets:
  - name: partner
    kind: repository
    repo: their-org/their-repo
    branch: main
"""
            )

    def test_a_duplicate_target_name_is_refused(self) -> None:
        with pytest.raises(ValueError, match="declared twice"):
            parse_promotion_contract(
                """
targets:
  - {name: example-prod, kind: environment, install: example, environment: prod}
  - {name: example-prod, kind: environment, install: example, environment: uat}
"""
            )

    def test_an_unknown_kind_is_refused(self) -> None:
        with pytest.raises(ValueError, match="kind must be one of"):
            parse_promotion_contract(
                "targets:\n  - {name: odd, kind: cluster}\n"
            )


    def test_a_suite_acceptance_is_admitted_with_its_coordinate(self) -> None:
        # `suite` shipped in REF-Promotion, the console, the dock and this file's
        # own scaffolded example while the validator still refused it, so a hand
        # that uncommented the template got "acceptance is probe or none".
        (target,) = parse_promotion_contract(
            "\n".join(
                [
                    "targets:",
                    "  - name: example-qa",
                    "    kind: environment",
                    "    install: example",
                    "    environment: qa",
                    "    acceptance: suite",
                    "    suite: https://ci.example/api/sit/latest",
                    "    suite_pass: '\"result\":\"passed\"'",
                ]
            )
        )
        assert target.acceptance == "suite"
        assert target.suite_url == "https://ci.example/api/sit/latest"
        assert target.suite_pass == '"result":"passed"'

    def test_a_suite_without_a_coordinate_is_refused(self) -> None:
        # Acceptance names where the verdict is published. A suite with nowhere
        # to read would derive unreadable forever while looking declared.
        with pytest.raises(ValueError, match="where the verdict is published"):
            parse_promotion_contract(
                "\n".join(
                    [
                        "targets:",
                        "  - name: example-qa",
                        "    kind: environment",
                        "    install: example",
                        "    environment: qa",
                        "    acceptance: suite",
                    ]
                )
            )

    def test_an_unknown_acceptance_is_refused(self) -> None:
        with pytest.raises(ValueError, match="acceptance is one of"):
            parse_promotion_contract(
                "\n".join(
                    [
                        "targets:",
                        "  - name: example-qa",
                        "    kind: environment",
                        "    install: example",
                        "    environment: qa",
                        "    acceptance: vibes",
                    ]
                )
            )

    def test_every_shape_the_scaffold_shows_is_a_shape_it_accepts(self) -> None:
        """The commented template parses once uncommented.

        A scaffold is the only place most operators ever read the contract's
        shape, so an example the validator beside it refuses is worse than no
        example: it teaches a shape and then rejects it. This uncomments the
        template's target block and parses it.
        """
        lines = render_promotion_contract().splitlines()
        block = [
            line[2:] if line.startswith("# ") else line[1:]
            for line in lines
            if line.startswith("#   ") or line.startswith("#     ")
        ]
        assert any("acceptance: suite" in line for line in block), (
            "the scaffold no longer shows a suite; this test would pass vacuously"
        )
        targets = parse_promotion_contract("targets:\n" + "\n".join(block))
        assert [t.name for t in targets] == ["example-prod", "example-qa", "partner"]
