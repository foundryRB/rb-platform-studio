"""Render an app's Keycloak realm blocks from one canonical template.

Like every other part of a team folder now, the skeleton (``team_skeleton``,
INT-SKELETON-001) and the database Job (``database_grant.py``), the realm blocks
are rendered from the studio-owned template below, never copied from a donor
app. The realm is a security
procedure, not identity boilerplate: a realm named for the app (the isolation
boundary), a realm-scoped admin, and the OIDC client the app's oauth2-proxy uses.
Copying a live
app's realm and substituting the name carries those invariants only when the
reference already happens to be clean; the studio owns the one canonical shape
itself and fills in the app name and host, so no ``STUDIO_REFERENCE_IDENTITY_APP``
can propagate a neighbour's drift. The identity isolation suite gates whatever this
renders, so correctness never rests on this template agreeing with any app.

Brokering is the install's, not the template's (platform ADR-045). The install declares zero
or more default brokers on its deploy branch, each naming its own alias, provider
id, and the secret holding its credentials, and this module splices whatever is
declared into every realm it grants: no vendor, no secret name, and no count is
written down here. An install declaring none gets realms with no
``identityProviders`` block at all, which sign in against the realm's own users and
work. After the grant the realm's providers are the team's: it keeps the default,
disables it, or declares its own with its own credentials from its own chart.

The one step that lives outside git, registering each declared broker's callback
with that IdP, is surfaced in the pull-request checklist, never rendered here.
"""

# The realm ConfigMap/Job template legitimately exceeds the line length; disable
# E501 for this file (the Python below stays within it).
# ruff: noqa: E501

from __future__ import annotations

import json
import re
from collections.abc import Sequence

import yaml

from studio.domain.model.default_broker import DefaultBroker

__all__ = [
    "APP_PLACEHOLDER",
    "BROKERS_PLACEHOLDER",
    "BROKER_ENVS_PLACEHOLDER",
    "HOST_PLACEHOLDER",
    "ALLOWLIST_FLOW_ALIAS",
    "broker_callback_url",
    "realm_issuer_url",
    "render_identity_blocks",
    "identity_blocks_are_isolation_clean",
]

APP_PLACEHOLDER = "<app>"
HOST_PLACEHOLDER = "<host>"
BROKERS_PLACEHOLDER = "<brokers>"
BROKER_ENVS_PLACEHOLDER = "<broker-envs>"

# The first-broker-login flow the grant renders alongside the declared defaults.
ALLOWLIST_FLOW_ALIAS = "first broker login allowlist"

# alias and providerId land unquoted in the realm YAML and the alias also becomes an
# env-var name, so both are held to a plain identifier; secret_ref is a Kubernetes
# object name. A declaration that fails these would otherwise render YAML that is
# broken, or worse, YAML that parses into something else.
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_K8S_NAME = re.compile(r"^[a-z0-9][a-z0-9.-]*$")

# The canonical realm blocks (ConfigMap + provisioning Job), <app>- and <host>-
# tokenized. No leading `---`: the concern-file appender adds the separator.
_REALM_BLOCKS_TEMPLATE = r"""# Keycloak realm for <app> (platform ADR-031, platform ADR-045), applied by keycloak-config-cli below.
# This app's own realm: the OIDC client its oauth2-proxy uses, a realm-admin scoped
# to this realm only, and whichever default brokers this install declares (each one's
# client id/secret substituted from the secret that declaration names, the same
# connection every realm on this install reuses). The app secrets substitute from
# the keycloak-<app> Secret, minted in-cluster in the app's namespace by the
# gen-keycloak-<app> generate-if-absent Job (platform ADR-034) and reflected here; nothing
# secret is stored in this ConfigMap.
apiVersion: v1
kind: ConfigMap
metadata:
  name: keycloak-realm-<app>
  namespace: identity
data:
  realm.yaml: |
    realm: <app>
    enabled: true
<brokers>
    clients:
      # oauth2-proxy's own client, and the only client this grant declares: a
      # server-side confidential flow, so it carries no webOrigins (a CORS grant
      # is meaningless without a browser flow) and cannot serve a public PKCE
      # client. An app needing more clients - an SPA's own flow, a native shell's
      # RFC 8252 loopback - declares them in ITS OWN chart, applied as its
      # realm-scoped <app>-admin; see the onboard-a-realm guide's team-owned
      # clients section. IMPORT_MANAGED_CLIENT below is what lets those survive.
      - clientId: <app>
        enabled: true
        protocol: openid-connect
        publicClient: false
        secret: $(env:OIDC_CLIENT_SECRET)
        standardFlowEnabled: true
        redirectUris:
          - https://<host>/oauth2/callback
    users:
      # The realm's own admin. It must be able to authenticate by DIRECT GRANT,
      # because that is how the app's chart applies the clients it declares for
      # itself (see the onboard-a-realm guide's team-owned clients section).
      # Keycloak's user profile makes email/firstName/lastName required, and a
      # user missing them is refused with "Account is not fully set up" - no
      # required action, nothing in the logs to point at it.
      #
      # The address is deliberately under .invalid, the RFC 2606 reserved TLD
      # that can never be registered. The realm's user list IS its access
      # allowlist and the google broker links an identity by trusted email, so a
      # routable address here would be a way in for whoever holds that mailbox.
      - username: <app>-admin
        enabled: true
        email: <app>-admin@<app>.invalid
        firstName: <app>
        lastName: admin
        emailVerified: true
        credentials:
          - type: password
            value: $(env:REALM_ADMIN_PASSWORD)
            temporary: false
        clientRoles:
          realm-management:
            - realm-admin
---
# Realm provisioning for <app>. keycloak-config-cli applies the realm above
# as the master admin. The realm owns its own config, so each declared default
# broker reuses this install's own credential for it while the app secrets come
# from the app-owned keycloak-<app> Secret (reflected into this namespace from the
# app). Clients, identity providers and flows are applied no-delete: this grant
# converges what it declares and leaves team-declared config alone (see below).
apiVersion: batch/v1
kind: Job
metadata:
  name: keycloak-<app>-provision
  namespace: identity
  annotations:
    argocd.argoproj.io/hook: PostSync
    argocd.argoproj.io/hook-delete-policy: BeforeHookCreation
spec:
  backoffLimit: 6
  activeDeadlineSeconds: 1200
  template:
    spec:
      restartPolicy: OnFailure
      containers:
        - name: config-cli
          image: adorsys/keycloak-config-cli:6.5.1-26.1.0
          env:
            - name: KEYCLOAK_URL
              value: http://keycloak-http.identity.svc.cluster.local
            - name: KEYCLOAK_USER
              valueFrom:
                secretKeyRef:
                  name: keycloak-admin
                  key: username
            - name: KEYCLOAK_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: keycloak-admin
                  key: password
            - name: KEYCLOAK_AVAILABILITYCHECK_ENABLED
              value: "true"
            - name: KEYCLOAK_AVAILABILITYCHECK_TIMEOUT
              value: 900s
            - name: IMPORT_VARSUBSTITUTION_ENABLED
              value: "true"
            # What this Job converges, and what it leaves standing. config-cli
            # defaults every resource type to full-managed, but only alongside its
            # remote state (import.remote-state.enabled, default true and left on
            # here), which scopes purging to "resources it created before". A client
            # or a provider a team declares for itself is not in this Job's remote
            # state and already survives its re-apply.
            #
            # These four say it structurally rather than leaving it contingent on
            # that attribute surviving a realm's life: the grant converges the
            # client and the brokers it declares and never deletes anything else,
            # which is the whole basis of team-owned clients and team-owned
            # identity providers. The env names drop the property's dashes
            # (import.managed.identity-provider -> IMPORT_MANAGED_IDENTITYPROVIDER),
            # the same binding IMPORT_VARSUBSTITUTION_ENABLED above shows; the
            # underscored spelling binds to nothing and fails silent.
            - name: IMPORT_MANAGED_CLIENT
              value: no-delete
            - name: IMPORT_MANAGED_IDENTITYPROVIDER
              value: no-delete
            - name: IMPORT_MANAGED_IDENTITYPROVIDERMAPPER
              value: no-delete
            - name: IMPORT_MANAGED_AUTHENTICATIONFLOW
              value: no-delete
            - name: IMPORT_FILES_LOCATIONS
              value: /config/realm.yaml
<broker-envs>
            - name: OIDC_CLIENT_SECRET
              valueFrom:
                secretKeyRef:
                  name: keycloak-<app>
                  key: clientSecret
            - name: REALM_ADMIN_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: keycloak-<app>
                  key: realmAdminPassword
          volumeMounts:
            - name: realm
              mountPath: /config
              readOnly: true
      volumes:
        - name: realm
          configMap:
            name: keycloak-realm-<app>"""


def broker_env_prefix(alias: str) -> str:
    """The env-var stem carrying one broker's credentials into the Job."""
    return "BROKER_" + re.sub(r"[^A-Za-z0-9]", "_", alias).upper()


def realm_issuer_url(host: str, app: str) -> str:
    """The realm's OIDC issuer, derived from the app's own hostname domain."""
    domain = host.split(".", 1)[1] if "." in host else "<platform domain>"
    return f"https://keycloak.{domain}/realms/{app}"


def broker_callback_url(host: str, app: str, alias: str) -> str:
    """One broker's callback on this realm, derived from the app's own hostname
    domain and that broker's alias (which is why an alias is registered with the
    IdP and not renamed casually afterwards: the alias fixes the path)."""
    return f"{realm_issuer_url(host, app)}/broker/{alias}/endpoint"


def _validate(brokers: Sequence[DefaultBroker]) -> None:
    seen: set[str] = set()
    for broker in brokers:
        if not _NAME.match(broker.alias):
            raise ValueError(f"broker alias {broker.alias!r} is not a plain identifier")
        if not _NAME.match(broker.provider_id):
            raise ValueError(
                f"broker {broker.alias!r} providerId {broker.provider_id!r} is not a "
                "plain identifier"
            )
        if not _K8S_NAME.match(broker.secret_ref):
            raise ValueError(
                f"broker {broker.alias!r} secretRef {broker.secret_ref!r} is not a "
                "Kubernetes object name"
            )
        if broker.alias in seen:
            raise ValueError(f"broker alias {broker.alias!r} is declared twice")
        seen.add(broker.alias)


def render_broker_blocks(brokers: Sequence[DefaultBroker]) -> str:
    """The realm's ``identityProviders`` and its allowlist flow, or nothing at all.

    Every declared broker brokers existing users only: its
    ``firstBrokerLoginFlowAlias`` points at the flow rendered below, whose two
    executions deny an account with no matching realm user rather than creating one
    (platform ADR-031). That is the shape of the default this install declares, not a rule
    about the realm: a team's own provider chooses its own flow.

    Credentials are never rendered. Each broker's client id and secret are
    ``$(env:...)`` substitutions the Job fills from that declaration's own Secret.
    """
    if not brokers:
        return ""
    lines = ["    identityProviders:"]
    for broker in brokers:
        prefix = broker_env_prefix(broker.alias)
        config: dict[str, object] = {
            "clientId": f"$(env:{prefix}_CLIENT_ID)",
            "clientSecret": f"$(env:{prefix}_CLIENT_SECRET)",
            "syncMode": "IMPORT",
        }
        config.update(broker.config)
        lines += [
            f"      - alias: {broker.alias}",
            f"        providerId: {broker.provider_id}",
            f"        displayName: {json.dumps(broker.display_name or broker.alias)}",
            "        enabled: true",
            # The allowlist links a pre-provisioned user by its trusted email, so the
            # broker's email claim has to be trusted for the link to happen at all.
            "        trustEmail: true",
            f"        firstBrokerLoginFlowAlias: {ALLOWLIST_FLOW_ALIAS}",
            "        config:",
        ]
        lines += [f"          {key}: {json.dumps(value)}" for key, value in config.items()]
    lines += [
        "    # Existing-users-only broker login (platform ADR-031): the realm's user list IS the",
        '    # allowlist. "Detect Existing Broker User" fails when no realm user matches',
        "    # the brokered identity by email, so an unknown upstream account is denied,",
        '    # never auto-created; "Automatically Set Existing User" links the',
        "    # pre-provisioned user by its trusted email with no prompt. Grant access by",
        "    # creating the user (with the email that IdP asserts) in this realm; revoke",
        "    # by disabling or deleting them.",
        "    authenticationFlows:",
        f"      - alias: {ALLOWLIST_FLOW_ALIAS}",
        "        description: Existing-users-only broker login (platform ADR-031); link a pre-provisioned user by trusted email, deny unknown upstream accounts.",
        "        providerId: basic-flow",
        "        topLevel: true",
        "        builtIn: false",
        "        authenticationExecutions:",
        "          - authenticator: idp-detect-existing-broker-user",
        "            requirement: REQUIRED",
        "          - authenticator: idp-auto-link",
        "            requirement: REQUIRED",
    ]
    return "\n".join(lines) + "\n"


def render_broker_envs(brokers: Sequence[DefaultBroker]) -> str:
    """The Job env carrying each declared broker's credentials in from its Secret."""
    if not brokers:
        return ""
    lines: list[str] = []
    for broker in brokers:
        prefix = broker_env_prefix(broker.alias)
        lines.append(
            f"            # The {broker.alias} broker this install declares, "
            "reused by every realm."
        )
        for env_suffix, key in (("CLIENT_ID", "clientId"), ("CLIENT_SECRET", "clientSecret")):
            lines += [
                f"            - name: {prefix}_{env_suffix}",
                "              valueFrom:",
                "                secretKeyRef:",
                f"                  name: {broker.secret_ref}",
                f"                  key: {key}",
            ]
    return "\n".join(lines) + "\n"


def render_identity_blocks(
    app: str, host: str, brokers: Sequence[DefaultBroker], login_theme: str = ""
) -> str:
    """The realm ConfigMap and provisioning Job for ``app`` at ``host``, rendered
    from the canonical template with the install's declared ``brokers`` spliced in.

    Validated isolation-clean (realm and client named for the app, the app credential
    sourced from the app-owned ``keycloak-<app>`` Secret, no literal credential in any
    broker) so a template regression fails closed here rather than downstream.

    ``brokers`` is passed, never defaulted: a caller that forgot it would silently
    render a realm with no brokering, or read every realm on the install as drifted.

    ``login_theme`` is the install's login theme (values.yaml identity.loginTheme.name);
    named, the realm carries it as ``loginTheme``, so the sign-in pages wear the
    install's look. Empty keeps Keycloak's own.
    """
    _validate(brokers)
    blocks = (
        _REALM_BLOCKS_TEMPLATE.replace(BROKERS_PLACEHOLDER + "\n", render_broker_blocks(brokers))
        .replace(BROKER_ENVS_PLACEHOLDER + "\n", render_broker_envs(brokers))
        .replace(APP_PLACEHOLDER, app)
        .replace(HOST_PLACEHOLDER, host)
    )
    if login_theme:
        blocks = blocks.replace(
            f"    realm: {app}\n    enabled: true\n",
            f"    realm: {app}\n    enabled: true\n    loginTheme: {login_theme}\n",
            1,
        )
    if not identity_blocks_are_isolation_clean(blocks_text=blocks, app=app):
        raise ValueError(
            "the canonical realm template did not render isolation-clean for "
            f"{app!r}; the template is broken"
        )
    return blocks


def _brokers_carry_no_literal_credential(blocks_text: str) -> bool:
    """No broker in the rendered realm carries a credential value of its own.

    The realm ConfigMap is committed to the install's deploy branch in the clear, so
    every credential-bearing field of every identity provider has to be a
    ``$(env:...)`` substitution the Job fills from a Secret. Provider-blind on
    purpose: it asks what a value is, never who the provider is.
    """
    try:
        documents = [doc for doc in yaml.safe_load_all(blocks_text) if isinstance(doc, dict)]
    except yaml.YAMLError:
        return False
    for document in documents:
        if document.get("kind") != "ConfigMap":
            continue
        try:
            realm = yaml.safe_load(document.get("data", {}).get("realm.yaml", "")) or {}
        except yaml.YAMLError:
            return False
        for provider in realm.get("identityProviders") or []:
            config = (provider or {}).get("config") or {}
            for key, value in config.items():
                if "secret" not in key.lower() and key.lower() != "clientid":
                    continue
                if not (isinstance(value, str) and value.startswith("$(env:")):
                    return False
    return True


def identity_blocks_are_isolation_clean(*, blocks_text: str, app: str) -> bool:
    """The realm is the app's own isolation boundary: named for the app, its client
    named for the app, its realm ConfigMap and provisioning Job named for the app,
    its app secrets sourced from the app-owned keycloak-<app> Secret, and no broker
    carrying a credential of its own. Mirrors the platform's identity isolation gate;
    a regression that leaves a placeholder, a cross-app name, or a literal credential
    fails here."""
    if APP_PLACEHOLDER in blocks_text or HOST_PLACEHOLDER in blocks_text:
        return False
    required = (
        f"realm: {app}",
        f"clientId: {app}",
        f"name: keycloak-realm-{app}",
        f"name: keycloak-{app}-provision",
        "secretKeyRef:",
    )
    has_app_secret = f"name: keycloak-{app}" in blocks_text
    if not (has_app_secret and all(token in blocks_text for token in required)):
        return False
    return _brokers_carry_no_literal_credential(blocks_text)
