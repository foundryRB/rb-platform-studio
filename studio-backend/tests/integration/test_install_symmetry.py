"""Per-install symmetry: an inherited foreign hostname or issuer is caught (foundry-platform#47)."""

from __future__ import annotations

from studio.domain.services.install_symmetry import symmetry_problems

_AUTHORING_CHART = {
    "host": "estimatekit.example.com",
    "auth": {"oidc": {"issuer": "https://keycloak.example.com/realms/estimatekit"}},
}


class TestSymmetryProblems:
    def test_the_inherited_defaults_incident_is_caught(self) -> None:
        # A deploy branch carrying images only inherits both chart defaults.
        problems = symmetry_problems(
            app="estimatekit",
            zone="example.org",
            deploy_values={"estimatekit": {"images": {"app": {"tag": "1.18.0"}}}},
            chart_values=_AUTHORING_CHART,
        )
        assert len(problems) == 2
        assert any("example.com" in p and "host" in p for p in problems)
        assert any("keycloak.example.com" in p for p in problems)
        assert all("example.org" in p for p in problems)

    def test_explicit_local_values_pass(self) -> None:
        assert (
            symmetry_problems(
                app="estimatekit",
                zone="example.org",
                deploy_values={
                    "estimatekit": {
                        "host": "estimatekit.example.org",
                        "auth": {
                            "oidc": {
                                "issuer": "https://keycloak.example.org/realms/estimatekit"
                            }
                        },
                    }
                },
                chart_values=_AUTHORING_CHART,
            )
            == []
        )

    def test_the_authoring_install_still_passes_on_its_own_defaults(self) -> None:
        # The authoring install inheriting its own defaults is correct, if
        # fragile; the row judges the zone, not whether the key was written down.
        assert (
            symmetry_problems(
                app="estimatekit",
                zone="example.com",
                deploy_values={"estimatekit": {"images": {}}},
                chart_values=_AUTHORING_CHART,
            )
            == []
        )

    def test_the_proxiverso_incident_is_caught(self) -> None:
        # The install-agnostic chart (INT-FOUNDRY-046) ships host empty on
        # purpose and guards its HTTPRoute with it; the studio's pre-1.22.1
        # standup rendered images only, so nothing anywhere set the host: no
        # route, no DNS record, stage promoted with an NXDOMAIN probe while
        # every git-side row stayed green (proxiverso, 2026-07-31).
        problems = symmetry_problems(
            app="proxiverso",
            zone="example.com",
            deploy_values={"proxiverso": {"images": {"app": {"tag": "1.1.1"}}}},
            chart_values={"host": ""},
        )
        assert len(problems) == 1
        assert "proxiverso.host" in problems[0]
        assert "deploy branch" in problems[0]

    def test_a_declared_empty_key_pinned_on_the_deploy_branch_passes(self) -> None:
        assert (
            symmetry_problems(
                app="proxiverso",
                zone="example.com",
                deploy_values={"proxiverso": {"host": "proxiverso.example.com"}},
                chart_values={"host": ""},
            )
            == []
        )

    def test_a_declared_empty_issuer_never_pinned_is_caught(self) -> None:
        # The same contract for the OIDC issuer: declared empty means "pin me
        # per install"; an empty render crash-loops the sidecar.
        problems = symmetry_problems(
            app="app",
            zone="example.com",
            deploy_values={"app": {"host": "app.example.com"}},
            chart_values={"host": "", "auth": {"oidc": {"issuer": ""}}},
        )
        assert len(problems) == 1
        assert "auth.oidc.issuer" in problems[0]

    def test_a_dormant_oidc_block_is_not_held_to_an_issuer(self) -> None:
        # The shape every scaffolded repo ships: the sidecar off, the
        # credential names pre-rendered, the issuer waiting on a realm grant.
        # The chart guards the proxy container on the flag, so there is no
        # sidecar to point anywhere and nothing to pin per install.
        assert (
            symmetry_problems(
                app="discord-warden",
                zone="example.com",
                deploy_values={"discord-warden": {"host": "discord-warden.example.com"}},
                chart_values={
                    "host": "",
                    "auth": {
                        "oidc": {
                            "enabled": False,
                            "existingSecret": "keycloak-discord-warden",
                            "issuer": "",
                        }
                    },
                },
            )
            == []
        )

    def test_the_deploy_branch_turning_the_sidecar_on_restores_the_issuer(self) -> None:
        # The realm grant's own act: the flag and the issuer land together on
        # the deploy branch, so an install that adopts OIDC and forgets the
        # issuer is caught in the same breath it turned the sidecar on.
        problems = symmetry_problems(
            app="discord-warden",
            zone="example.com",
            deploy_values={
                "discord-warden": {
                    "host": "discord-warden.example.com",
                    "auth": {"oidc": {"enabled": True}},
                }
            },
            chart_values={"host": "", "auth": {"oidc": {"enabled": False, "issuer": ""}}},
        )
        assert len(problems) == 1
        assert "auth.oidc.issuer" in problems[0]

    def test_a_block_declaring_no_flag_at_all_stays_judged(self) -> None:
        # Silence is live, never dormant: the fleet's charts predate the flag,
        # and estimatekit's foreign issuer sat in exactly such a block. Reading
        # silence as off would hand that incident straight back.
        problems = symmetry_problems(
            app="estimatekit",
            zone="example.org",
            deploy_values={"estimatekit": {"host": "estimatekit.example.org"}},
            chart_values=_AUTHORING_CHART,
        )
        assert len(problems) == 1
        assert "keycloak.example.com" in problems[0]

    def test_an_absent_key_is_never_a_problem(self) -> None:
        # A chart declaring no auth at all is not required to grow one.
        assert (
            symmetry_problems(
                app="solveos",
                zone="example.org",
                deploy_values={"solveos": {"host": "solveos.example.org"}},
                chart_values={"host": "solveos.example.com"},
            )
            == []
        )

    def test_a_deploy_override_that_is_itself_foreign_is_caught(self) -> None:
        # Copying another install's values file wholesale, the other half of
        # the same anti-pattern.
        problems = symmetry_problems(
            app="protopane",
            zone="example.org",
            deploy_values={"protopane": {"host": "protopane.example.com"}},
            chart_values=None,
        )
        assert len(problems) == 1
        assert "deploy branch" in problems[0]

    def test_unreadable_legs_and_missing_zone_report_nothing(self) -> None:
        assert (
            symmetry_problems(app="x", zone="example.org", deploy_values=None, chart_values=None)
            == []
        )
        assert (
            symmetry_problems(app="x", zone="", deploy_values=None, chart_values=_AUTHORING_CHART)
            == []
        )

    def test_ports_schemes_and_trailing_dots_do_not_fool_the_match(self) -> None:
        assert (
            symmetry_problems(
                app="app",
                zone="example.org",
                deploy_values={
                    "app": {
                        "host": "app.example.org.",
                        "auth": {
                            "oidc": {"issuer": "https://keycloak.example.org:8443/realms/app"}
                        },
                    }
                },
                chart_values=None,
            )
            == []
        )
        # A zone that merely ends with the same letters is not in the zone.
        assert (
            symmetry_problems(
                app="app",
                zone="example.org",
                deploy_values={"app": {"host": "app.myexample.org"}},
                chart_values=None,
            )
            != []
        )
