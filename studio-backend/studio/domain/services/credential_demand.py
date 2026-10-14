"""Platform-minted credentials: the chart's demand against the install's grant.

Three of an app's Secrets exist only because a grant's generate-if-absent Job
mints them in the cluster: the Keycloak realm credential (``keycloak-<app>``),
the Postgres role password (``pg-app-<app>``), and the event-bus nkey seed
(``nats-<app>``; the signed JWT it pairs with, ``nats-jwt-<app>``, derives
from it and is judged through it). The demand side is the app chart's own text
- a ``existingSecret`` or ``seedSecret`` naming one of them - and the provide
side is the install branch's ``teams/<app>/`` folder carrying the matching
generator (``gen-keycloak-<app>``, ``gen-pg-app-<app>``, ``gen-nats-<app>``).

A chart that names one with no grant to mint it schedules a pod that waits
forever on a Secret nothing will ever create. Nothing goes red on the way
there: the values parse, the templates render, the release publishes, and the
failure surfaces days later as ``CreateContainerConfigError`` on the cluster
(task-api shipped exactly that and sat broken for 12+ hours). Neither half's
own CI can see it - the app's runner holds no platform credential, and the
platform's runner checks out no app repo - so the cross-check belongs where
both halves are already in reach: the studio, which serves the install's
deploy branch and reads app repos over the repo host.

The demand is read off the chart's ``values.yaml``, where the fleet's charts
carry every credential name as a Secret-naming value that the templates then
reference through ``.Values``. Any key ending ``secret`` (``existingSecret``,
``secret``, ``secretName``) counts: three charts wire the credential correctly
under ``database.secret`` and reading only ``existingSecret`` made them
invisible here, which is a hole in the check rather than a shape to police.

The check runs in BOTH directions, because only one of them catches a name the
app invented:

- demand without grant: the chart names a credential no grant mints, so the
  pod waits forever on a Secret nothing creates.
- grant without demand: the install manifest carries the capability but the
  chart names no credential for it. Something else is in that slot - an
  invented name (knight-fight shipped ``knight-fight-oidc`` and
  ``knight-fight-db`` and served 503 for sixteen hours), a hardcoded template
  literal, or nothing at all.

The second direction exists because the first cannot see a substitution. An
unrecognised name is not a violation of a name-matching rule, it is the
ABSENCE of one, and absence read as "not applicable" is how a dead pod passes
green. Anchoring on the grant - a fact the install manifest states, which no
app chart can talk itself out of - is what makes the vacuous pass impossible.

A capability block explicitly ``enabled: false`` is dormant, not a demand: the
scaffold ships every block off, carrying the correct names so a later adoption
flips a flag instead of authoring a literal. Dormant plus granted is still a
finding - the grant exists and the chart is not consuming it.

Enablement is judged on the EFFECTIVE value, the deploy branch's override over
the chart default, the same way the per-install hostname check reads it. A
chart may legitimately default a capability off so it still installs standalone
and let the deploy branch (where the credential actually exists) turn it on;
shoot4fun does exactly that. Reading the chart default alone would call that
correct, live app a finding.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

__all__ = [
    "DEMAND_GRANT_ROW",
    "credential_demands",
    "credential_mismatches",
    "effective_values",
    "ungranted_credential_demands",
]

# The conformance row this check reports as, parametrized per app. Named here
# with the check itself so the runner that emits it, the gate that treats it
# as advisory, the pull-request body that warns on it, and the status link
# that reads it all agree by construction.
DEMAND_GRANT_ROW = "install/credentials::demand-grant"

# Each platform-minted credential: the Secret an app's chart names, the
# generator the install's teams/<app>/ folder must carry to mint it, and the
# skill that renders that grant.
_CREDENTIALS = (
    ("identity", "keycloak-{app}", "gen-keycloak-{app}", "foundry-onboard-keycloak"),
    ("database", "pg-app-{app}", "gen-pg-app-{app}", "foundry-onboard-database"),
    ("events", "nats-{app}", "gen-nats-{app}", "foundry-onboard-events"),
)

_CREDENTIALS_BY_KIND = {kind: secret for kind, secret, _generator, _skill in _CREDENTIALS}


def effective_values(
    *,
    app: str,
    chart_values: Mapping[str, object] | None,
    deploy_values: Mapping[str, object] | None,
) -> dict[str, object]:
    """The chart defaults with the install's deploy override applied.

    The deploy branch nests its keys under the app name (the chart ships as a
    dependency), so the override is ``deploy_values[app]``. Judging either half
    alone misreads a live app: the chart default is what the app ships with,
    the override is what the install actually runs.
    """
    merged: dict[str, object] = dict(chart_values or {})
    override = (deploy_values or {}).get(app)
    if isinstance(override, Mapping):
        merged = _deep_merge(merged, override)
    return merged


def _deep_merge(base: Mapping[str, object], over: Mapping[str, object]) -> dict[str, object]:
    out = dict(base)
    for key, value in over.items():
        current = out.get(key)
        if isinstance(current, Mapping) and isinstance(value, Mapping):
            out[key] = _deep_merge(current, value)
        else:
            out[key] = value
    return out


def credential_demands(*, app: str, values: Mapping[str, object]) -> tuple[str, ...]:
    """The platform-minted credentials the app's chart values name and consume.

    Every Secret-naming leaf anywhere in the values is collected, so a
    credential named under any block (``auth.oidc``, ``postgres``, or one a
    future chart adds) counts as a demand; a leaf naming an app-owned secret
    (an external fact the operator applies) matches no credential and is
    ignored. A name sitting under a block turned ``enabled: false`` is dormant
    and does not demand its grant yet.
    """
    named = frozenset(_named_secrets(values))
    return tuple(
        kind
        for kind, secret, _generator, _skill in _CREDENTIALS
        if secret.format(app=app) in named and not _is_disabled(app=app, kind=kind, values=values)
    )


def credential_mismatches(
    *, app: str, values: Mapping[str, object], granted: Iterable[str]
) -> tuple[str, ...]:
    """Grants ``teams/<app>/`` carries that the app's chart does not name.

    The direction ``ungranted_credential_demands`` structurally cannot see: a
    chart that substituted its own name for the platform's is not a chart with
    a bad name, it is a chart with NO recognised name, and every check keyed on
    matching a literal reads that as nothing to judge.

    ``granted`` is the same input the demand direction takes - every
    ``metadata.name`` in the team folder - so both directions are judged
    against one source of truth: the generator Job's presence IS the grant.
    A granted capability whose credential the chart never names is a finding
    whatever the reason - an invented name, a hardcoded template literal, or a
    chart that simply never wired it.
    """
    names = frozenset(granted)
    named = frozenset(_named_secrets(values))
    problems: list[str] = []
    for kind, secret, generator, skill in _CREDENTIALS:
        if generator.format(app=app) not in names:
            continue
        want = secret.format(app=app)
        if want not in named:
            problems.append(
                f"teams/{app}/ grants {kind} but the chart names no {want}; a chart "
                f"that substitutes its own name schedules a pod that waits forever "
                f"on a Secret nothing creates. Name it in k8s/values.yaml (the "
                f"{skill} grant mints exactly this one)"
            )
        elif _is_disabled(app=app, kind=kind, values=values):
            problems.append(
                f"teams/{app}/ grants {kind} and the chart names {want}, but its "
                f"block is enabled: false, so nothing consumes the grant"
            )
    return tuple(problems)


def ungranted_credential_demands(
    *, app: str, values: Mapping[str, object], granted: Iterable[str]
) -> tuple[str, ...]:
    """The demands in the app's chart values that ``teams/<app>/`` does not grant.

    ``granted`` is every ``metadata.name`` the team folder's documents carry;
    a demand is satisfied by the presence of its generator among them. A chart
    naming no platform-minted credential is vacuously clean.
    """
    names = frozenset(granted)
    problems: list[str] = []
    for kind, secret, generator, skill in _CREDENTIALS:
        if kind not in credential_demands(app=app, values=values):
            continue
        if generator.format(app=app) in names:
            continue
        problems.append(
            f"the chart names {secret.format(app=app)} but teams/{app}/ carries "
            f"no {kind} grant to mint it, so the pod waits forever on a Secret "
            f"nothing creates (run {skill})"
        )
    return tuple(problems)


# The values keys the fleet's charts use to name a Secret. Matched on the
# suffix rather than a fixed list so `secret`, `existingSecret` and
# `secretName` all read alike: three charts wire the credential correctly under
# `database.secret`, and a check that saw only `existingSecret` judged them as
# naming nothing.
def _is_secret_key(key: object) -> bool:
    if not isinstance(key, str):
        return False
    lowered = key.lower()
    return lowered.endswith("secret") or lowered.endswith("secretname")


def _named_secrets(node: object) -> list[str]:
    """Every Secret-naming string leaf anywhere in a values tree."""
    found: list[str] = []
    if isinstance(node, Mapping):
        for key, child in node.items():
            if _is_secret_key(key) and isinstance(child, str):
                found.append(child)
            else:
                found.extend(_named_secrets(child))
    elif isinstance(node, list):
        for child in node:
            found.extend(_named_secrets(child))
    return found


def _is_disabled(*, app: str, kind: str, values: Mapping[str, object]) -> bool:
    """Whether the block naming this credential is explicitly turned off.

    Only an explicit ``enabled: false`` in the same block as the credential's
    name counts. A block with no ``enabled`` key at all is live - the fleet's
    charts predate the flag, and defaulting silence to "off" would re-open the
    vacuous pass this check exists to close.
    """
    return _block_disabled(values, _CREDENTIALS_BY_KIND[kind].format(app=app))


def _block_disabled(node: object, secret: str) -> bool:
    if isinstance(node, Mapping):
        names_it = any(
            _is_secret_key(k) and isinstance(v, str) and v == secret for k, v in node.items()
        )
        if names_it and node.get("enabled") is False:
            return True
        return any(_block_disabled(child, secret) for child in node.values())
    if isinstance(node, list):
        return any(_block_disabled(child, secret) for child in node)
    return False
