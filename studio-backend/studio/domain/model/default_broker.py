"""One default broker the install declares on its deploy branch (ADR-045)."""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["DefaultBroker"]


@dataclass(frozen=True)
class DefaultBroker:
    """An upstream IdP this install brokers by default, as declared in values.yaml.

    The install declares zero or more of these; the identity grant splices whatever
    is declared into every realm it renders. The platform writes down no vendor, no
    secret name and no count, so an install brokering Entra, or five providers, or
    none at all, is a declaration rather than a code change.

    ``alias`` is the realm-facing name and fixes the callback path
    (``/realms/<app>/broker/<alias>/endpoint``), so it is registered with that IdP
    and never changed casually afterwards. ``provider_id`` is Keycloak's own
    provider kind (``google``, ``oidc``, ``saml``, whatever that Keycloak ships).
    ``secret_ref`` names the Secret in the ``identity`` namespace holding this
    broker's ``clientId`` and ``clientSecret`` keys; the install seeded it and names
    it for what it holds. ``config`` is the rest of that provider's non-secret
    configuration, merged over the credential substitutions the grant renders, and
    is where a provider's own coordinates live (an ``oidc`` provider's authorization
    and token URLs, a ``google`` provider's ``useJwksUrl``).
    """

    alias: str
    provider_id: str
    secret_ref: str
    display_name: str = ""
    config: dict[str, object] = field(default_factory=dict)
