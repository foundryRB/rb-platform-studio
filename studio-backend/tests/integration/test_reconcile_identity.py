"""INT-GRANT-010: a granted realm re-rendered from the current template and declaration.

A realm carries what it was rendered with until it is reconciled (ADR-045), and
until now nothing reconciled it: onboard_identity refuses an app whose realm
exists and reconcile_app leaves every grant file alone. This is the repair, and
these tests hold what it touches (the realm ConfigMap and its provisioning Job),
what it carries (the users the branch admitted) and what it never touches (the
app's own credential and its generator, the other grants, every other byte).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from pytest_intent import intent

from studio.adapters.inbound.http.app import create_app
from studio.domain.model.default_broker import DefaultBroker
from studio.domain.services.identity_grant import render_identity_blocks
from studio.domain.services.identity_reconcile import (
    carry_admitted_users,
    realm_facts,
    reconcile_identity_documents,
)
from studio.domain.services.secret_generator import keycloak_secret, render_secret_generator
from studio.domain.services.team_documents import (
    GRANT_FILES,
    append_document,
    find_document,
    replace_document,
    split_by_concern,
)
from tests.conftest import FakeGitPr, StubConformance, build_container

_APP = "beta-app"
_HOST = "beta-app.lab.example.dev"
_BETA = Path("teams") / _APP

# The fixture's declaration, and the same install after it declares a second
# broker: the ADR-045 migration an install performs after granting realms.
_ENTRA = """  - alias: entra
    providerId: oidc
    secretRef: keycloak-entra
    displayName: Entra ID
    config:
      authorizationUrl: "https://login.microsoftonline.test/authorize"
"""
_THEME = """identity:
  loginTheme:
    name: example-theme
"""

_ADMITTED = (
    "      # Ops lead, admitted by hand.\n"
    "      - username: someone\n"
    "        email: someone@example.test\n"
    "        enabled: true\n"
    "        emailVerified: true\n"
)


def _declare_entra(root: Path) -> None:
    values = root / "values.yaml"
    values.write_text(values.read_text(encoding="utf-8") + _ENTRA, encoding="utf-8")


def _name_theme(root: Path) -> None:
    values = root / "values.yaml"
    values.write_text(values.read_text(encoding="utf-8") + _THEME, encoding="utf-8")


def _read(root: Path, filename: str) -> str:
    return (root / _BETA / filename).read_text(encoding="utf-8")


def _realm(config_text: str) -> dict:
    config_map = next(
        doc
        for doc in yaml.safe_load_all(config_text)
        if isinstance(doc, dict) and doc.get("kind") == "ConfigMap"
    )
    return yaml.safe_load(config_map["data"]["realm.yaml"])


def _provision_env(jobs_text: str) -> dict[str, dict]:
    job = next(
        doc
        for doc in yaml.safe_load_all(jobs_text)
        if isinstance(doc, dict) and doc["metadata"]["name"] == f"keycloak-{_APP}-provision"
    )
    return {e["name"]: e for e in job["spec"]["template"]["spec"]["containers"][0]["env"]}


def _admit_someone(root: Path) -> None:
    """A person admitted to the realm by hand, ahead of the admin the template renders."""
    config = root / _BETA / "config.yaml"
    text = config.read_text(encoding="utf-8")
    marker = f"      - username: {_APP}-admin\n"
    assert marker in text
    config.write_text(text.replace(marker, _ADMITTED + marker, 1), encoding="utf-8")


def _grant_credential(root: Path) -> dict[str, str]:
    """The app's own credential generator, appended the way onboard_identity
    appends it, so the folder carries the whole grant; returns the texts of every
    grant file afterwards, the byte-for-byte baseline a re-render must keep."""
    generator = render_secret_generator(_APP, keycloak_secret(_APP))
    for filename, doc in split_by_concern(generator):
        path = root / _BETA / filename
        existing = path.read_text(encoding="utf-8") if path.exists() else None
        path.write_text(append_document(existing, doc), encoding="utf-8")
    return {
        filename: (root / _BETA / filename).read_text(encoding="utf-8")
        for filename in sorted(GRANT_FILES)
        if (root / _BETA / filename).exists()
    }


class TestReconcileIdentityDomain:
    """The pure re-render over a folder, without a gate in the way."""

    _ONE = (DefaultBroker("google", "google", "keycloak-google", "Google", {"useJwksUrl": "true"}),)
    _TWO = _ONE + (DefaultBroker("entra", "oidc", "keycloak-entra", "Entra ID"),)

    @staticmethod
    def _folder(rendered: str) -> dict[str, str]:
        files: dict[str, str] = {}
        for filename, doc in split_by_concern(rendered):
            files[filename] = append_document(files.get(filename), doc)
        return files

    @intent("INT-GRANT-010")
    def test_an_unchanged_declaration_is_current_and_changes_no_file(self) -> None:
        rendered = render_identity_blocks(_APP, _HOST, self._ONE)
        result = reconcile_identity_documents(
            app=_APP, rendered_blocks=rendered, team_files=self._folder(rendered)
        )
        assert result.current
        assert result.files == ()
        assert result.previous_aliases == ("google",)

    @intent("INT-GRANT-010")
    def test_only_the_grants_own_documents_change_and_the_rest_is_byte_identical(self) -> None:
        """The concern files carry other grants' documents beside the realm's (the
        database Jobs, the credential generator); a re-render addresses the realm's
        two documents by kind and name and leaves every other byte alone."""
        files = self._folder(render_identity_blocks(_APP, _HOST, self._ONE))
        other = (
            "# A neighbour's document.\napiVersion: batch/v1\nkind: Job\n"
            "metadata:\n  name: gen-pg-app-beta-app\n"
        )
        files["jobs.yaml"] = other + "---\n" + files["jobs.yaml"]
        files["serviceaccount.yaml"] = (
            "apiVersion: v1\nkind: ServiceAccount\nmetadata:\n  name: x\n"
        )
        fresh = render_identity_blocks(_APP, _HOST, self._TWO)
        result = reconcile_identity_documents(app=_APP, rendered_blocks=fresh, team_files=files)
        changed = dict(result.files)
        assert set(changed) == {"config.yaml", "jobs.yaml"}
        assert changed["jobs.yaml"].startswith(other + "---\n")
        assert find_document(changed["jobs.yaml"], kind="Job", name="gen-pg-app-beta-app") == (
            other.strip("\n")
        )
        # And the re-rendered documents are exactly the fresh render's, byte for byte.
        expected = self._folder(fresh)
        assert changed["config.yaml"] == expected["config.yaml"]
        assert changed["jobs.yaml"] == other + "---\n" + expected["jobs.yaml"]

    @intent("INT-GRANT-010")
    def test_an_admitted_user_is_carried_across_verbatim_and_the_admin_re_rendered(
        self,
    ) -> None:
        """THE regression a re-render must never commit: the users list is the access
        allowlist, so the person someone admitted by hand survives with the exact
        text they wrote, while the platform's own admin is the template's."""
        rendered = render_identity_blocks(_APP, _HOST, self._ONE)
        existing = find_document(rendered, kind="ConfigMap", name=f"keycloak-realm-{_APP}")
        assert existing is not None
        # The admin hand-edited too, which the template wins back.
        existing = existing.replace(f"        firstName: {_APP}\n", "        firstName: Edited\n")
        existing = existing.replace(
            f"      - username: {_APP}-admin\n", _ADMITTED + f"      - username: {_APP}-admin\n"
        )
        fresh = find_document(
            render_identity_blocks(_APP, _HOST, self._TWO),
            kind="ConfigMap",
            name=f"keycloak-realm-{_APP}",
        )
        assert fresh is not None
        merged, carried = carry_admitted_users(fresh, existing, _APP)
        assert carried == ("someone",)
        assert _ADMITTED.strip("\n") in merged
        realm = yaml.safe_load(yaml.safe_load(merged)["data"]["realm.yaml"])
        users = {user["username"]: user for user in realm["users"]}
        assert set(users) == {f"{_APP}-admin", "someone"}
        assert users[f"{_APP}-admin"]["firstName"] == _APP
        assert users["someone"]["email"] == "someone@example.test"
        assert [p["alias"] for p in realm["identityProviders"]] == ["google", "entra"]
        # Without an admitted user the merge is the fresh render itself.
        untouched, none = carry_admitted_users(fresh, fresh, _APP)
        assert untouched == fresh and none == ()

    @intent("INT-GRANT-010")
    def test_a_hand_applied_provider_is_superseded_by_the_declaration(self) -> None:
        """The install that motivated this: realms carrying a provider applied by
        hand under the alias the install then declared. Everything but the users
        is the template's, so the hand-applied block gives way to the render."""
        files = self._folder(render_identity_blocks(_APP, _HOST, ()))
        hand_applied = (
            "    identityProviders:\n"
            "      - alias: cloudflare\n"
            "        providerId: oidc\n"
            "        enabled: true\n"
            "        config:\n"
            "          clientId: $(env:CLOUDFLARE_CLIENT_ID)\n"
            "          clientSecret: $(env:CLOUDFLARE_CLIENT_SECRET)\n"
        )
        files["config.yaml"] = files["config.yaml"].replace(
            "    clients:\n", hand_applied + "    clients:\n", 1
        )
        assert realm_facts(files["config.yaml"]) == (("cloudflare",), "")
        declared = (
            DefaultBroker(
                "cloudflare", "oidc", "keycloak-cloudflare", "Cloudflare",
                {"authorizationUrl": "https://team.cloudflareaccess.test/authorize"},
            ),
        )
        result = reconcile_identity_documents(
            app=_APP,
            rendered_blocks=render_identity_blocks(_APP, _HOST, declared, "example-theme"),
            team_files=files,
        )
        realm = _realm(dict(result.files)["config.yaml"])
        providers = {p["alias"]: p for p in realm["identityProviders"]}
        assert set(providers) == {"cloudflare"}
        assert providers["cloudflare"]["config"]["clientId"] == "$(env:BROKER_CLOUDFLARE_CLIENT_ID)"
        assert providers["cloudflare"]["firstBrokerLoginFlowAlias"]
        assert realm["loginTheme"] == "example-theme"
        assert result.previous_aliases == ("cloudflare",)

    def test_replace_document_keeps_every_other_byte(self) -> None:
        config_map = "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: x"
        text = f"a: 1\n---\n# kept comment\n{config_map}\n---\nb: 2\n"
        replaced = replace_document(text, f"{config_map}\ndata: {{}}", kind="ConfigMap", name="x")
        assert replaced == f"a: 1\n---\n{config_map}\ndata: {{}}\n---\nb: 2\n"
        assert replace_document(text, "kind: Job", kind="Job", name="x") is None
        assert find_document(text, kind="ConfigMap", name="x") == f"# kept comment\n{config_map}"


class TestReconcileIdentity:
    """The verb through the HTTP door, on the gate-validate-rollback path."""

    @intent("INT-GRANT-010")
    def test_reconcile_adds_a_newly_declared_broker_to_an_existing_realm(
        self, client: TestClient, platform_root: Path, fake_git: FakeGitPr
    ) -> None:
        _declare_entra(platform_root)
        response = client.post("/api/reconcile/identity", json={"name": _APP})
        assert response.status_code == 200, response.text
        realm = _realm(_read(platform_root, "config.yaml"))
        assert [p["alias"] for p in realm["identityProviders"]] == ["google", "entra"]
        env = _provision_env(_read(platform_root, "jobs.yaml"))
        assert env["BROKER_ENTRA_CLIENT_SECRET"]["valueFrom"]["secretKeyRef"]["name"] == (
            "keycloak-entra"
        )
        assert env["BROKER_GOOGLE_CLIENT_ID"]["valueFrom"]["secretKeyRef"]["name"] == (
            "keycloak-google"
        )
        body = response.json()
        assert body["changed_files"] == [f"teams/{_APP}/config.yaml", f"teams/{_APP}/jobs.yaml"]
        assert body["branch"] == f"reconcile/{_APP}-identity"
        assert fake_git.prepared == [f"reconcile/{_APP}-identity"]
        assert fake_git.finalized[0]["commit_message"] == f"fix(identity): reconcile {_APP} realm"
        pr_body = fake_git.finalized[0]["pr_body"]
        assert "### What changed and why" in pr_body
        assert "`entra`: newly declared" in pr_body
        assert "`google`: already brokered" in pr_body
        # The operator's step: the new alias's callback, and only the new one.
        assert "Register the `entra` callback" in pr_body
        assert f"https://keycloak.lab.example.dev/realms/{_APP}/broker/entra/endpoint" in pr_body
        assert "Register the `google` callback" not in pr_body
        assert "the `google` callback" in pr_body and "stands" in pr_body

    @intent("INT-GRANT-010")
    def test_reconcile_is_refused_before_any_branch_when_the_realm_is_current(
        self, client: TestClient, platform_root: Path, fake_git: FakeGitPr
    ) -> None:
        before = {f: _read(platform_root, f) for f in ("config.yaml", "jobs.yaml")}
        response = client.post("/api/reconcile/identity", json={"name": _APP})
        assert response.status_code == 409, response.text
        assert "nothing to reconcile" in response.json()["detail"]
        assert fake_git.prepared == [] and fake_git.finalized == []
        assert {f: _read(platform_root, f) for f in before} == before

    @intent("INT-GRANT-010")
    def test_reconcile_never_rewrites_the_app_credential_or_the_other_grants(
        self, client: TestClient, platform_root: Path, fake_git: FakeGitPr
    ) -> None:
        baseline = _grant_credential(platform_root)
        _declare_entra(platform_root)
        db_jobs_before = [
            doc
            for doc in yaml.safe_load_all(baseline["jobs.yaml"])
            if isinstance(doc, dict) and "keycloak" not in doc["metadata"]["name"]
        ]
        response = client.post("/api/reconcile/identity", json={"name": _APP})
        assert response.status_code == 200, response.text
        # The generator's ServiceAccount and RBAC files did not change at all.
        assert _read(platform_root, "serviceaccount.yaml") == baseline["serviceaccount.yaml"]
        assert _read(platform_root, "grant-rbac.yaml") == baseline["grant-rbac.yaml"]
        assert response.json()["changed_files"] == [
            f"teams/{_APP}/config.yaml",
            f"teams/{_APP}/jobs.yaml",
        ]
        # In jobs.yaml the generator Job and the database grant's Jobs are the
        # same bytes; only the realm's provisioning Job moved.
        jobs = _read(platform_root, "jobs.yaml")
        generator = find_document(jobs, kind="Job", name=f"gen-keycloak-{_APP}")
        assert generator is not None and f"keycloak-{_APP}" in generator
        assert generator == find_document(
            baseline["jobs.yaml"], kind="Job", name=f"gen-keycloak-{_APP}"
        )
        db_jobs_after = [
            doc
            for doc in yaml.safe_load_all(jobs)
            if isinstance(doc, dict) and "keycloak" not in doc["metadata"]["name"]
        ]
        assert db_jobs_after == db_jobs_before
        # The realm still names the same client, host and app credential.
        realm = _realm(_read(platform_root, "config.yaml"))
        assert [c["clientId"] for c in realm["clients"]] == [_APP]
        assert realm["clients"][0]["redirectUris"] == [f"https://{_HOST}/oauth2/callback"]
        env = _provision_env(jobs)
        assert env["OIDC_CLIENT_SECRET"]["valueFrom"]["secretKeyRef"]["name"] == f"keycloak-{_APP}"

    @intent("INT-GRANT-010")
    def test_a_reconciled_realm_is_byte_identical_to_a_fresh_onboarding(
        self, platform_root: Path, tmp_path: Path
    ) -> None:
        """Two installs, one declaration: one granted alpha-app's realm under it
        from the start, the other granted under the old declaration and then
        reconciled. Their config.yaml and jobs.yaml must be the same bytes."""
        fresh_root = tmp_path / "fresh"
        shutil.copytree(platform_root, fresh_root)
        _declare_entra(fresh_root)
        _name_theme(fresh_root)
        fresh = TestClient(create_app(build_container(fresh_root, StubConformance(), FakeGitPr())))
        assert fresh.post("/api/onboard/identity", json={"name": "alpha-app"}).status_code == 200

        git = FakeGitPr()
        stale = TestClient(create_app(build_container(platform_root, StubConformance(), git)))
        assert stale.post("/api/onboard/identity", json={"name": "alpha-app"}).status_code == 200
        _declare_entra(platform_root)
        _name_theme(platform_root)
        response = stale.post("/api/reconcile/identity", json={"name": "alpha-app"})
        assert response.status_code == 200, response.text

        for filename in ("config.yaml", "jobs.yaml", "serviceaccount.yaml", "grant-rbac.yaml"):
            ours = (platform_root / "teams" / "alpha-app" / filename).read_text(encoding="utf-8")
            theirs = (fresh_root / "teams" / "alpha-app" / filename).read_text(encoding="utf-8")
            assert ours == theirs, filename
        reconciled = (platform_root / "teams" / "alpha-app" / "config.yaml").read_text(
            encoding="utf-8"
        )
        assert _realm(reconciled)["loginTheme"] == "example-theme"
        assert [p["alias"] for p in _realm(reconciled)["identityProviders"]] == ["google", "entra"]
        # And the reconcile is now a no-op on both sides.
        assert stale.post("/api/reconcile/identity", json={"name": "alpha-app"}).status_code == 409
        assert fresh.post("/api/reconcile/identity", json={"name": "alpha-app"}).status_code == 409

    @intent("INT-GRANT-010")
    def test_reconcile_carries_an_admitted_user_across(
        self, client: TestClient, platform_root: Path, fake_git: FakeGitPr
    ) -> None:
        _admit_someone(platform_root)
        _declare_entra(platform_root)
        response = client.post("/api/reconcile/identity", json={"name": _APP})
        assert response.status_code == 200, response.text
        config = _read(platform_root, "config.yaml")
        assert _ADMITTED.strip("\n") in config
        users = [u["username"] for u in _realm(config)["users"]]
        assert sorted(users) == sorted([f"{_APP}-admin", "someone"])
        assert "carried across untouched" in fake_git.finalized[0]["pr_body"]
        assert "`someone`" in fake_git.finalized[0]["pr_body"]
        # Carried once: reconciling again finds nothing to do.
        assert client.post("/api/reconcile/identity", json={"name": _APP}).status_code == 409

    @intent("INT-GRANT-010")
    def test_reconcile_applies_a_newly_named_login_theme(
        self, client: TestClient, platform_root: Path, fake_git: FakeGitPr
    ) -> None:
        _name_theme(platform_root)
        response = client.post("/api/reconcile/identity", json={"name": _APP})
        assert response.status_code == 200, response.text
        assert _realm(_read(platform_root, "config.yaml"))["loginTheme"] == "example-theme"
        body = fake_git.finalized[0]["pr_body"]
        assert "`keycloak default` -> `example-theme`" in body
        # The one declared broker was already on the realm: converged, not new.
        assert "`google`: already brokered" in body
        assert "newly declared" not in body
        # Only the ConfigMap moved; the Job has no theme in it.
        assert response.json()["changed_files"] == [f"teams/{_APP}/config.yaml"]

    @intent("INT-GRANT-010")
    def test_the_reconciled_realm_is_isolation_clean(
        self, client: TestClient, platform_root: Path
    ) -> None:
        """The same claims onboarding asserts (INT-GRANT-002/005/008) over what a
        reconcile writes back: named for the app, credential from the app-owned
        Secret, no literal broker credential, existing-users-only brokering."""
        _declare_entra(platform_root)
        assert client.post("/api/reconcile/identity", json={"name": _APP}).status_code == 200
        realm = _realm(_read(platform_root, "config.yaml"))
        assert realm["realm"] == _APP
        for provider in realm["identityProviders"]:
            assert provider["config"]["clientSecret"].startswith("$(env:")
            assert provider["firstBrokerLoginFlowAlias"] == "first broker login allowlist"
        env = _provision_env(_read(platform_root, "jobs.yaml"))
        assert env["IMPORT_MANAGED_IDENTITYPROVIDER"]["value"] == "no-delete"
        admin_password = env["REALM_ADMIN_PASSWORD"]["valueFrom"]["secretKeyRef"]
        assert admin_password["name"] == f"keycloak-{_APP}"

    def test_a_failed_gate_restores_the_realm_byte_identical(
        self, failing_client: TestClient, platform_root: Path, fake_git: FakeGitPr
    ) -> None:
        _declare_entra(platform_root)
        before = {f: _read(platform_root, f) for f in ("config.yaml", "jobs.yaml")}
        response = failing_client.post("/api/reconcile/identity", json={"name": _APP})
        assert response.status_code == 422
        assert {f: _read(platform_root, f) for f in before} == before
        assert fake_git.aborted == [f"reconcile/{_APP}-identity"]
        assert fake_git.finalized == []

    def test_an_app_without_a_realm_is_404(self, client: TestClient) -> None:
        response = client.post("/api/reconcile/identity", json={"name": "alpha-app"})
        assert response.status_code == 404
        assert "identity realm" in response.json()["detail"]

    def test_an_unknown_app_is_404(self, client: TestClient) -> None:
        assert client.post("/api/reconcile/identity", json={"name": "ghost-app"}).status_code == 404

    @pytest.mark.parametrize("payload", [{"name": ""}, {}])
    def test_the_name_is_validated(self, client: TestClient, payload: dict) -> None:
        assert client.post("/api/reconcile/identity", json=payload).status_code == 422
