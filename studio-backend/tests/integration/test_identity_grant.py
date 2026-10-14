"""INT-GRANT-002: the Keycloak realm blocks are rendered from the studio's own
canonical template, fully tokenized and validated isolation-clean -- not mirrored
from a live reference app whose drift a rename would carry."""

from __future__ import annotations

import pytest
import yaml
from pytest_intent import intent

import studio.domain.services.identity_grant as grant_mod
from studio.domain.model.default_broker import DefaultBroker
from studio.domain.services.identity_grant import (
    ALLOWLIST_FLOW_ALIAS,
    APP_PLACEHOLDER,
    HOST_PLACEHOLDER,
    identity_blocks_are_isolation_clean,
    render_identity_blocks,
)

# One declared broker: the ordinary install.
_ONE = (
    DefaultBroker("google", "google", "keycloak-google", "Google", {"useJwksUrl": "true"}),
)


@intent("INT-GRANT-002")
@pytest.mark.parametrize("app", ["scrapyard", "sabbito-bazarrito", "alpha-app"])
def test_rendered_realm_is_isolation_clean_for_any_app(app: str) -> None:
    blocks = render_identity_blocks(app, f"{app}.example.com", _ONE)
    # Fully substituted: no placeholder token survives.
    assert APP_PLACEHOLDER not in blocks
    assert HOST_PLACEHOLDER not in blocks
    # The named app owns the realm everywhere it matters (the isolation boundary).
    assert f"realm: {app}" in blocks
    assert f"clientId: {app}" in blocks
    assert f"name: keycloak-realm-{app}" in blocks
    assert f"name: keycloak-{app}-provision" in blocks
    # The app credential is sourced from the app-owned keycloak-<app> Secret.
    assert f"name: keycloak-{app}" in blocks
    assert "secretKeyRef:" in blocks
    # The host is the app's own, not another app's.
    assert f"https://{app}.example.com/oauth2/callback" in blocks
    assert identity_blocks_are_isolation_clean(blocks_text=blocks, app=app)


def test_render_fails_closed_if_the_template_regresses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Were the template ever edited to leave a placeholder or a cross-app realm
    name, rendering raises rather than shipping a realm the isolation gate rejects."""
    broken = grant_mod._REALM_BLOCKS_TEMPLATE.replace("realm: <app>", "realm: shared")
    monkeypatch.setattr(grant_mod, "_REALM_BLOCKS_TEMPLATE", broken)
    with pytest.raises(ValueError, match="isolation-clean"):
        render_identity_blocks("scrapyard", "scrapyard.example.com", _ONE)


@intent("INT-GRANT-005")
@pytest.mark.parametrize("app", ["scrapyard", "alexandria", "alpha-app"])
def test_grant_leaves_team_declared_clients_standing(app: str) -> None:
    """The grant declares one client and applies clients no-delete, so a client an
    app declares in its OWN chart survives the platform's next re-apply. Without
    this, config-cli's default full-managed mode deletes every client absent from
    the grant's import file (foundry-platform#123)."""
    blocks = render_identity_blocks(app, f"{app}.example.com", _ONE)
    job = list(yaml.safe_load_all(blocks))[1]
    container = job["spec"]["template"]["spec"]["containers"][0]
    env = {e["name"]: e.get("value") for e in container["env"]}
    assert env.get("IMPORT_MANAGED_CLIENT") == "no-delete"


@intent("INT-GRANT-005")
def test_grants_only_client_is_confidential_and_carries_no_web_origins() -> None:
    """oauth2-proxy's client is server-side: a CORS grant on it is meaningless, and
    its presence is what made a browser flow look supported on a client whose
    publicClient: false forbids one. A public PKCE flow gets its own client,
    declared in the app's chart -- never this one widened."""
    blocks = render_identity_blocks("scrapyard", "scrapyard.example.com", _ONE)
    realm = yaml.safe_load(list(yaml.safe_load_all(blocks))[0]["data"]["realm.yaml"])
    clients = realm["clients"]
    assert [c["clientId"] for c in clients] == ["scrapyard"]
    assert clients[0]["publicClient"] is False
    assert "webOrigins" not in clients[0]


@intent("INT-GRANT-005")
@pytest.mark.parametrize("app", ["scrapyard", "alexandria"])
def test_realm_admin_can_authenticate_by_direct_grant(app: str) -> None:
    """The app's chart applies its own clients as this admin, so the admin must be
    able to log in. Keycloak's user profile makes email/firstName/lastName
    required and refuses a user missing them with "Account is not fully set up" -
    no required action set, nothing in the logs naming the cause. The address must
    stay under .invalid (RFC 2606, never registrable): the realm's user list is
    its access allowlist and the google broker links by trusted email, so a
    routable address here would admit whoever holds that mailbox."""
    blocks = render_identity_blocks(app, f"{app}.example.com", _ONE)
    realm = yaml.safe_load(list(yaml.safe_load_all(blocks))[0]["data"]["realm.yaml"])
    admin = [u for u in realm["users"] if u["username"] == f"{app}-admin"][0]
    assert admin["firstName"] and admin["lastName"]
    assert admin["emailVerified"] is True
    assert admin["email"].endswith(".invalid"), admin["email"]


_TWO = (
    DefaultBroker("google", "google", "keycloak-google", config={"useJwksUrl": "true"}),
    DefaultBroker(
        "entra",
        "oidc",
        "keycloak-entra",
        "Entra ID",
        {"authorizationUrl": "https://login.microsoftonline.test/authorize"},
    ),
)


def _realm_of(blocks: str) -> dict:
    return yaml.safe_load(list(yaml.safe_load_all(blocks))[0]["data"]["realm.yaml"])


def _env_of(blocks: str) -> list[dict]:
    job = list(yaml.safe_load_all(blocks))[1]
    return job["spec"]["template"]["spec"]["containers"][0]["env"]


@intent("INT-GRANT-008")
def test_an_install_declaring_no_broker_gets_a_realm_that_brokers_nothing() -> None:
    """The broker is the install's, and none is a supported install rather than a
    missing value: the realm comes up with no identityProviders block, no allowlist
    flow, and no broker credential in the Job, signing in against its own users."""
    blocks = render_identity_blocks("scrapyard", "scrapyard.example.com", ())
    realm = _realm_of(blocks)
    assert "identityProviders" not in realm
    assert "authenticationFlows" not in realm
    assert realm["clients"] and realm["users"]
    assert not [e for e in _env_of(blocks) if e["name"].startswith("BROKER_")]


@intent("INT-GRANT-008")
def test_every_declared_broker_is_rendered_against_its_own_secret() -> None:
    """No vendor, no secret name and no count is written into the template: each
    declaration brings its own alias, provider id and Secret, and an install
    declaring several gets several."""
    blocks = render_identity_blocks("scrapyard", "scrapyard.example.com", _TWO)
    providers = _realm_of(blocks)["identityProviders"]
    assert [p["alias"] for p in providers] == ["google", "entra"]
    assert [p["providerId"] for p in providers] == ["google", "oidc"]
    # Each provider's non-secret config rides through untouched.
    assert providers[1]["config"]["authorizationUrl"] == (
        "https://login.microsoftonline.test/authorize"
    )
    secrets = {
        e["name"]: e["valueFrom"]["secretKeyRef"]["name"]
        for e in _env_of(blocks)
        if e["name"].startswith("BROKER_")
    }
    assert secrets == {
        "BROKER_GOOGLE_CLIENT_ID": "keycloak-google",
        "BROKER_GOOGLE_CLIENT_SECRET": "keycloak-google",
        "BROKER_ENTRA_CLIENT_ID": "keycloak-entra",
        "BROKER_ENTRA_CLIENT_SECRET": "keycloak-entra",
    }


@intent("INT-GRANT-008")
@pytest.mark.parametrize("brokers", [_ONE, _TWO])
def test_a_declared_broker_brokers_existing_users_only(brokers: tuple) -> None:
    """The allowlist is the shape of the default the install declares, so it renders
    with any non-empty declaration and for every provider in it: an account with no
    matching realm user is denied at detection, never created (ADR-031). A team's own
    provider picks its own flow; this says nothing about those."""
    blocks = render_identity_blocks("scrapyard", "scrapyard.example.com", brokers)
    realm = _realm_of(blocks)
    flows = {f["alias"]: f for f in realm["authenticationFlows"]}
    assert set(p["firstBrokerLoginFlowAlias"] for p in realm["identityProviders"]) == {
        ALLOWLIST_FLOW_ALIAS
    }
    allowlist = flows[ALLOWLIST_FLOW_ALIAS]["authenticationExecutions"]
    executions = [e["authenticator"] for e in allowlist]
    assert executions == ["idp-detect-existing-broker-user", "idp-auto-link"]
    assert "idp-create-user-if-unique" not in executions


@intent("INT-GRANT-002")
def test_a_broker_carrying_a_literal_credential_fails_closed() -> None:
    """The realm ConfigMap is committed in the clear, so a declaration that put a
    credential in its own config (rather than leaving it to the Secret the
    declaration names) must not render. Provider-blind: it asks what the value is."""
    leaky = (
        DefaultBroker("google", "google", "keycloak-google", config={"clientSecret": "hunter2"}),
    )
    with pytest.raises(ValueError, match="isolation-clean"):
        render_identity_blocks("scrapyard", "scrapyard.example.com", leaky)


@intent("INT-GRANT-005")
def test_the_grant_leaves_team_declared_providers_and_flows_standing() -> None:
    """The converge keeps what the grant declares and deletes nothing else, so a
    provider or flow a team declares for itself survives the platform's re-apply
    without depending on the remote-state attribute outliving the realm."""
    blocks = render_identity_blocks("scrapyard", "scrapyard.example.com", _ONE)
    env = {e["name"]: e.get("value") for e in _env_of(blocks)}
    assert env["IMPORT_MANAGED_CLIENT"] == "no-delete"
    assert env["IMPORT_MANAGED_IDENTITYPROVIDER"] == "no-delete"
    assert env["IMPORT_MANAGED_IDENTITYPROVIDERMAPPER"] == "no-delete"
    assert env["IMPORT_MANAGED_AUTHENTICATIONFLOW"] == "no-delete"


@pytest.mark.parametrize(
    "bad",
    [
        DefaultBroker("has space", "google", "keycloak-google"),
        DefaultBroker("google", "goo gle", "keycloak-google"),
        DefaultBroker("google", "google", "Keycloak_Google"),
    ],
)
def test_a_malformed_declaration_is_refused_rather_than_rendered(bad: DefaultBroker) -> None:
    """alias and providerId land unquoted in the realm YAML and the alias becomes an
    env-var name, so a declaration that is not a plain identifier would render YAML
    that is broken or, worse, parses into something else."""
    with pytest.raises(ValueError):
        render_identity_blocks("scrapyard", "scrapyard.example.com", (bad,))


def test_the_same_alias_twice_is_refused() -> None:
    """Two providers with one alias collide on both the realm key and the env stem."""
    twice = (
        DefaultBroker("google", "google", "keycloak-google"),
        DefaultBroker("google", "oidc", "keycloak-other"),
    )
    with pytest.raises(ValueError, match="declared twice"):
        render_identity_blocks("scrapyard", "scrapyard.example.com", twice)


@intent("INT-GRANT-009")
def test_realm_names_the_installs_login_theme_and_only_then() -> None:
    """A named theme lands as the realm's loginTheme; none named, none rendered."""
    named = render_identity_blocks("acme", "acme.example.test", (), login_theme="example-theme")
    realm = next(
        yaml.safe_load(doc["data"]["realm.yaml"])
        for doc in yaml.safe_load_all(named)
        if isinstance(doc, dict) and doc.get("kind") == "ConfigMap"
    )
    assert realm["realm"] == "acme"
    assert realm["loginTheme"] == "example-theme"
    assert identity_blocks_are_isolation_clean(blocks_text=named, app="acme")

    bare = render_identity_blocks("acme", "acme.example.test", ())
    assert "loginTheme" not in bare

