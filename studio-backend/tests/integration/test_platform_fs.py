"""FsPlatformRepository tests: byte-preserving manifest edits, team-folder parsing."""

from __future__ import annotations

from pathlib import Path

import pytest

from studio.adapters.outbound.platform_fs.fs_platform_repository import FsPlatformRepository
from studio.domain.exceptions.pause_conflict_error import PauseConflictError
from studio.domain.services.team_documents import pause_application, resume_application


def test_manifest_parses_roles_and_derives_mcp_urls(platform_root: Path) -> None:
    repository = FsPlatformRepository(platform_root)
    entries = {entry.name: entry for entry in repository.manifest_entries()}
    assert list(entries) == ["alpha-app", "beta-app"]
    assert entries["alpha-app"].role == "parts"
    assert entries["beta-app"].role == "output"
    # mcp: true derives the URL from the zone; nothing stores it.
    assert entries["alpha-app"].mcp_url == "https://alpha-app.lab.example.dev/mcp"
    assert entries["beta-app"].mcp_url is None
    assert repository.zone() == "lab.example.dev"


def test_mcp_url_follows_the_gateway_hostname(platform_root: Path) -> None:
    """A flagged app on a short host advertises its MCP there, not at <name>.<zone>.

    external-dns publishes the record from the Gateway listener, so the derived
    name would hand every consumer of the fleet view - the connect menu, the HTTP
    API, get_app - an endpoint that resolves nowhere.
    """
    gateway = platform_root / "teams" / "alpha-app" / "gateway.yaml"
    gateway.write_text(
        gateway.read_text(encoding="utf-8").replace(
            "hostname: alpha-app.lab.example.dev", "hostname: a1.lab.example.dev"
        ),
        encoding="utf-8",
    )
    entries = {e.name: e for e in FsPlatformRepository(platform_root).manifest_entries()}
    assert entries["alpha-app"].mcp_url == "https://a1.lab.example.dev/mcp"


def test_mcp_url_falls_back_to_the_convention_without_a_team_folder(
    platform_root: Path,
) -> None:
    """A flagged entry whose folder has not merged yet has no listener to read."""
    manifest = platform_root / "foundry.yaml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8")
        + "- name: ghost-app\n  display: Ghost\n  icon: mdi-ghost\n  mcp: true\n",
        encoding="utf-8",
    )
    entries = {e.name: e for e in FsPlatformRepository(platform_root).manifest_entries()}
    assert entries["ghost-app"].mcp_url == "https://ghost-app.lab.example.dev/mcp"


def test_add_manifest_entry_inserts_sorted_and_keeps_comments(platform_root: Path) -> None:
    repository = FsPlatformRepository(platform_root)
    repository.add_manifest_entry(
        name="abc-app", display="ABC App", icon="mdi-abc", mcp=False, role="output"
    )
    text = (platform_root / "foundry.yaml").read_text(encoding="utf-8")
    assert text.index("# Test install manifest (ADR-032).") == 0
    assert "# The output the install built and runs." in text
    assert text.index("- name: abc-app") < text.index("- name: beta-app")
    assert text.index("output:") < text.index("- name: abc-app")
    assert "mcp:" not in text.split("- name: abc-app")[1].split("- name:")[0]
    assert [entry.name for entry in repository.manifest_entries()] == [
        "alpha-app",
        "abc-app",
        "beta-app",
    ]


def test_add_manifest_entry_records_a_repo_that_differs(platform_root: Path) -> None:
    """Onboarding already accepts the repository to render the Application's
    repoURL; recording it in the manifest is what lets the manifest's OWN
    readers reach it - the chart's homepage bookmarks among them, since Helm
    reads the manifest and never the teams/ folder."""
    repository = FsPlatformRepository(platform_root)
    repository.add_manifest_entry(
        name="abc-app", display="ABC App", icon="mdi-abc", mcp=False, role="output",
        repo="fleet-abc-app",
    )
    text = (platform_root / "foundry.yaml").read_text(encoding="utf-8")
    entry = text.split("- name: abc-app")[1].split("- name:")[0]
    assert "repo: fleet-abc-app" in entry
    entries = {e.name: e for e in repository.manifest_entries()}
    assert entries["abc-app"].repo == "fleet-abc-app"
    assert entries["abc-app"].repo_name == "fleet-abc-app"


def test_add_manifest_entry_omits_a_repo_equal_to_the_name(platform_root: Path) -> None:
    """An app shipping from a repository of its own name declares nothing, so
    existing manifests take no churn and a `repo:` line in the file always means
    exactly one thing: these two identities are not the same string here. The
    undeclared entry still RESOLVES, because the default lives in one place."""
    repository = FsPlatformRepository(platform_root)
    repository.add_manifest_entry(
        name="abc-app", display="ABC App", icon="mdi-abc", mcp=False, role="output",
        repo="abc-app",
    )
    text = (platform_root / "foundry.yaml").read_text(encoding="utf-8")
    assert "repo:" not in text.split("- name: abc-app")[1].split("- name:")[0]
    entries = {e.name: e for e in repository.manifest_entries()}
    assert entries["abc-app"].repo == ""
    assert entries["abc-app"].repo_name == "abc-app"


def test_add_manifest_entry_opens_an_empty_role_block(tmp_path: Path) -> None:
    """A bare install's manifest carries a role it has no entries of yet as an
    empty flow sequence (`output: []`). The first entry of that role opens the
    block in place: one `output:` key, the entry under it, nothing appended at
    the end of the file.

    Read as an absent header, it grew a SECOND top-level `output:` key instead,
    and the manifest went on parsing only because YAML takes the last of a
    duplicate pair - the shape this install's own manifest was left in.
    """
    manifest = (
        "install: example\n"
        "ground: home\n"
        "parts:\n"
        "- name: platform-studio\n"
        "  display: Platform Studio\n"
        "  icon: mdi-source-branch-check\n"
        "output: []\n"
    )
    (tmp_path / "foundry.yaml").write_text(manifest, encoding="utf-8")
    (tmp_path / "values.yaml").write_text("zone: example.org\n", encoding="utf-8")
    (tmp_path / "teams").mkdir()

    repository = FsPlatformRepository(tmp_path)
    repository.add_manifest_entry(
        name="solveos", display="SolveOS", icon="mdi-puzzle-outline", mcp=False, role="output"
    )

    written = (tmp_path / "foundry.yaml").read_text(encoding="utf-8")
    assert written.count("output:") == 1
    assert "output: []" not in written
    assert "output:\n- name: solveos" in written
    assert "parts:\n- name: platform-studio" in written  # untouched
    entries = {entry.name: entry for entry in repository.manifest_entries()}
    assert entries["solveos"].role == "output"
    assert entries["platform-studio"].role == "parts"


def test_add_manifest_entry_creates_missing_role_block(tmp_path: Path) -> None:
    """A fresh install that has so far only onboarded its own tooling (all
    `parts`, no `output` app yet) still onboards its first output app: the
    absent block header is created fresh, not raised as a SyncFailedError."""
    manifest = (
        "install: example\n"
        "ground: home\n"
        "parts:\n"
        "- name: platform-studio\n"
        "  display: Platform Studio\n"
        "  icon: mdi-source-branch-check\n"
    )
    (tmp_path / "foundry.yaml").write_text(manifest, encoding="utf-8")
    (tmp_path / "values.yaml").write_text("zone: example.org\n", encoding="utf-8")
    (tmp_path / "teams").mkdir()

    repository = FsPlatformRepository(tmp_path)
    repository.add_manifest_entry(
        name="solveos", display="SolveOS", icon="mdi-puzzle-outline", mcp=False, role="output"
    )

    written = (tmp_path / "foundry.yaml").read_text(encoding="utf-8")
    assert "parts:\n- name: platform-studio" in written  # untouched
    assert written.index("output:") > written.index("parts:")
    assert "- name: solveos" in written
    entries = {entry.name: entry for entry in repository.manifest_entries()}
    assert entries["solveos"].role == "output"
    assert entries["platform-studio"].role == "parts"


def test_add_manifest_entry_into_parts_with_mcp_flag(platform_root: Path) -> None:
    repository = FsPlatformRepository(platform_root)
    repository.add_manifest_entry(
        name="zz-tool", display="ZZ Tool", icon="mdi-zz", mcp=True, role="parts"
    )
    text = (platform_root / "foundry.yaml").read_text(encoding="utf-8")
    entry_block = text.split("- name: zz-tool")[1].split("- name:")[0]
    assert "display: ZZ Tool" in entry_block
    assert "mcp: true" in entry_block
    assert text.index("parts:") < text.index("- name: zz-tool") < text.index("output:")
    entries = {entry.name: entry for entry in repository.manifest_entries()}
    assert entries["zz-tool"].role == "parts"
    assert entries["zz-tool"].mcp_url == "https://zz-tool.lab.example.dev/mcp"


def test_team_folder_facts_parse(platform_root: Path) -> None:
    repository = FsPlatformRepository(platform_root)
    alpha = repository.team_manifest("alpha-app")
    beta = repository.team_manifest("beta-app")
    assert alpha is not None and beta is not None
    assert alpha.hostname == "alpha-app.lab.example.dev"
    assert alpha.repo_url == "https://github.com/Test-Org/alpha-app"
    assert alpha.target_revision == "deploy-test"
    assert alpha.display_name == "Alpha App"
    assert alpha.icon == "mdi-alpha"
    assert alpha.has_database is False
    assert alpha.has_identity is False
    assert alpha.paused is False
    assert beta.has_database is True
    assert beta.has_identity is True
    assert repository.team_manifest("missing-app") is None
    assert repository.team_files("missing-app") == ()
    assert "application.yaml" in repository.team_files("alpha-app")


def test_raw_delete_prunes_the_emptied_folder(platform_root: Path) -> None:
    """A rolled-back onboarding leaves no stray teams/<app>/ shell behind."""
    repository = FsPlatformRepository(platform_root)
    repository.write_team_file("gamma-app", "namespace.yaml", "kind: Namespace\n")
    assert (platform_root / "teams" / "gamma-app").is_dir()
    repository.raw_delete("teams/gamma-app/namespace.yaml")
    assert not (platform_root / "teams" / "gamma-app").exists()
    assert (platform_root / "teams").is_dir()  # the shared parent survives


def test_pause_and_resume_round_trip_the_application_file(platform_root: Path) -> None:
    repository = FsPlatformRepository(platform_root)
    original = repository.team_file_text("alpha-app", "application.yaml")
    assert original is not None

    repository.write_team_file(
        "alpha-app", "application.yaml", pause_application(original, app="alpha-app")
    )
    paused = repository.team_manifest("alpha-app")
    assert paused is not None and paused.paused is True

    resumed_text = resume_application(pause_application(original, app="alpha-app"), app="alpha-app")
    assert resumed_text == original  # resume restores the file byte-for-byte
    repository.write_team_file("alpha-app", "application.yaml", resumed_text)
    running = repository.team_manifest("alpha-app")
    assert running is not None and running.paused is False


def test_pause_refuses_a_foreign_helm_block() -> None:
    # An Application whose source already carries a helm block (reserved for the
    # override, ADR-030): pause must refuse, not emit a duplicate helm key.
    manifest = (
        "apiVersion: argoproj.io/v1alpha1\n"
        "kind: Application\n"
        "metadata:\n"
        "  name: alpha-app\n"
        "spec:\n"
        "  source:\n"
        "    repoURL: https://github.com/Test-Org/alpha-app\n"
        "    targetRevision: deploy\n"
        "    path: prod\n"
        "    helm:\n"
        "      valuesObject:\n"
        "        alpha-app:\n"
        "          image:\n"
        "            tag: '1.2.3'\n"
        "  destination:\n"
        "    namespace: alpha-app\n"
    )
    with pytest.raises(PauseConflictError):
        pause_application(manifest, app="alpha-app")


def test_claims_parse_the_platform_intent(platform_root: Path) -> None:
    repository = FsPlatformRepository(platform_root)
    claims = {claim.claim_id: claim for claim in repository.claims()}
    assert claims["INT-TEST-001"].criticality == "critical"
    assert claims["INT-TEST-001"].scope == "integration"
    assert "bijection" not in claims["INT-TEST-001"].summary  # statement text, verbatim
    assert claims["INT-TEST-002"].summary == "Apps MUST ship a Dockerfile."
