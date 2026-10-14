"""Per-install symmetry: values that must be this install's own facts.

An app chart carries defaults for its hostname and its OIDC issuer, and those
defaults belong to whichever install the chart was authored against. A deploy
branch that omits the key inherits them silently, so a second install serves
the first install's hostname and points its OIDC sidecar at the first
install's realm - a healthy platform in front of a crash-looping app, with
nothing in the manifest, the teams folder, or the Application to show for it
(the per-install symmetry anti-pattern; foundry-platform#47).

The install-agnostic chart shape (INT-FOUNDRY-046) fails the other way
around: the chart deliberately ships the key EMPTY and guards what consumes
it, so a deploy branch that never pins the key renders the guarded objects
out of existence instead of serving a foreign zone. That is how proxiverso
shipped on chaos (2026-07-31): chart ``host: ""``, a standup-rendered branch
carrying images only, so no HTTPRoute rendered, external-dns published
nothing, and the app stalled at stage promoted with an NXDOMAIN probe while
every git-side check stayed green.

The effective value is what Helm renders: the deploy branch's per-install
override when it sets one, else the chart's own default. This module judges
that effective value against the install's own zone, so an inherited foreign
default fails where an explicit local one passes - and judges a declared key
with no effective value at all as its own failure. Deploy values nest under
the app name (the deploy chart declares the app chart as a dependency); the
app chart's own values are top-level.

A key belonging to a capability the values switch off is not judged at all.
The chart guards its oauth2-proxy sidecar on ``auth.oidc.enabled``, so a
dormant block renders no sidecar, and an issuer naming nothing is what a
realm grant later fills in (``foundry-onboard-keycloak`` pins it on the
deploy branch alongside the flag). That is the shape every scaffolded repo
ships - the block off, carrying the credential names the platform will
mint - and the flag is read the same effective way as the values it guards,
so the act that turns the capability on brings its issuer back under
judgment in the same breath.
"""

from __future__ import annotations

__all__ = ["symmetry_problems"]

# The values that must name this install, each with the flag that decides
# whether it is live. Both values are established conventions of the app-chart
# contract, and both are what broke when psa inherited chaos's: the hostname
# the app serves and answers Host on, and the realm its OIDC sidecar
# authenticates against. The hostname has no flag - an app always serves
# somewhere - while the issuer's is the sidecar's own switch.
_JUDGED_KEYS: tuple[tuple[tuple[str, ...], tuple[str, ...] | None], ...] = (
    (("host",), None),
    (("auth", "oidc", "issuer"), ("auth", "oidc", "enabled")),
)


def _dig(values: object, path: tuple[str, ...]) -> object:
    """The value at a dotted path, or None if any leg is missing."""
    node = values
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def _domain(value: str) -> str:
    """The DNS name in a bare hostname or a URL, without scheme, port, or path."""
    text = value.strip()
    if "://" in text:
        text = text.split("://", 1)[1]
    text = text.split("/", 1)[0]
    text = text.rsplit("@", 1)[-1]
    return text.split(":", 1)[0].rstrip(".").lower()


def _in_zone(domain: str, zone: str) -> bool:
    zone = zone.strip().rstrip(".").lower()
    return bool(domain) and bool(zone) and (domain == zone or domain.endswith(f".{zone}"))


def _dormant(*, scoped: object, chart_values: object, guard: tuple[str, ...] | None) -> bool:
    """Whether the capability a judged key belongs to is switched off.

    Read on the effective flag - the deploy branch's override over the chart
    default - the same precedence the judged values take, so a chart that
    defaults a capability off and an install that turns it on is read as live
    (the shape ``credential_demand`` reads for the same blocks). Only an
    explicit ``False`` is dormant: a block carrying no flag at all is live,
    because reading silence as off would re-open the inherited-issuer hole
    this module exists to close.
    """
    if guard is None:
        return False
    override = _dig(scoped, guard)
    if isinstance(override, bool):
        return not override
    return _dig(chart_values, guard) is False


def symmetry_problems(
    *,
    app: str,
    zone: str,
    deploy_values: dict | None,
    chart_values: dict | None,
) -> list[str]:
    """Effective values naming a foreign DNS zone, or declared and never set.

    Judges only keys the chart actually carries and the values leave live: a
    chart that declares no ``auth.oidc`` at all is not required to grow one,
    so an absent key is never a problem, and a block turned ``enabled: false``
    renders nothing that could read the key. A live key the chart DOES declare
    - even empty, the install-agnostic shape - must end up with a non-empty
    effective value in this install's zone. Returns one message per offending
    key, naming where the value came from, since the fix differs (an inherited
    default is fixed on the deploy branch; an explicit wrong value is fixed
    where it is written).
    """
    if not zone:
        return []
    problems: list[str] = []
    scoped = _dig(deploy_values, (app,)) if isinstance(deploy_values, dict) else None
    for path, guard in _JUDGED_KEYS:
        if _dormant(scoped=scoped, chart_values=chart_values, guard=guard):
            continue
        dotted = ".".join(path)
        override = _dig(scoped, path)
        default = _dig(chart_values, path)
        effective, origin = (
            (override, f"{app}.{dotted} on the deploy branch")
            if isinstance(override, str) and override.strip()
            else (default, f"{dotted} inherited from the app chart's own values")
        )
        if not isinstance(effective, str) or not effective.strip():
            # The chart declares the key but nothing gives it a value: the
            # install-agnostic shape renders the objects guarded by it out of
            # existence (an empty host skips the HTTPRoute, so external-dns
            # publishes no record; an empty issuer crash-loops the sidecar).
            # An unreadable chart (default None) stays a skip, never a guess.
            if default is not None:
                problems.append(
                    f"{app}.{dotted} is declared by the app chart as a "
                    f"per-install fact (empty default, INT-FOUNDRY-046) and "
                    f"never pinned for this install: Helm renders it empty and "
                    f"whatever consumes it drops out silently. Pin the key "
                    f"explicitly under {app!r} in the deploy branch's "
                    f"values.yaml."
                )
            continue
        domain = _domain(effective)
        if not _in_zone(domain, zone):
            problems.append(
                f"{origin} resolves to {domain!r}, which is not in this install's "
                f"zone {zone!r} (value: {effective.strip()!r}). Pin the key "
                f"explicitly under {app!r} in the deploy branch's values.yaml."
            )
    return problems
