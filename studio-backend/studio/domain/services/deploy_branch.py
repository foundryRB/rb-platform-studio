"""Render an app's deploy-<install> branch content from its declaration.

The deploy branch is the team's running state (ADR-025): per declared
environment, a Chart.yaml pinning the published app chart from GHCR and a
values.yaml carrying one repository+tag pair per released image - exactly the
paths the Image Updater bindings write and the chart reads - plus this
install's own hostname. Everything here derives from facts the onboarding
already holds (the app name, the org, the declared components, the install's
zone and its environment list) plus the two version facts read off GHCR (the
latest published chart and image tags), so the branch is deterministic: the
same declaration against the same registry state renders the same branch.

``host`` is rendered explicitly even though the chart carries a default,
because that default is whichever install the chart was authored against.
A branch that omits the key inherits it silently, so a second install
serves the first install's hostname and points its OIDC sidecar at the
first install's realm - healthy platform, crash-looping app (the
per-install symmetry anti-pattern; foundry-platform#47).
Rendering the key makes the install's own fact visible in the file a team
reads, copies, and edits.
"""

from __future__ import annotations

__all__ = ["deploy_branch_file_order", "render_deploy_branch"]


def deploy_branch_file_order(environments: tuple[str, ...]) -> tuple[str, ...]:
    """The branch's files in apply-read order: per declared environment, in
    declaration order, its Chart.yaml then its values.yaml. Every environment
    carries the same config shape (INT-FOUNDRY-020); the team tunes them
    apart later if it ever needs to."""
    return tuple(
        f"{env}/{filename}"
        for env in environments
        for filename in ("Chart.yaml", "values.yaml")
    )

# Rendered at the top of every values.yaml: the file a team copies when it
# stands up its next environment or install, so the rule travels with it.
_VALUES_HEADER = (
    "# Per-install values. Keys here are THIS install's own facts, pinned\n"
    "# explicitly: the app chart's defaults belong to whichever install it was\n"
    "# authored against, and an omitted key inherits them silently.\n"
    "# Add auth.oidc.enabled: true and auth.oidc.issuer here when this app is\n"
    "# granted an identity realm: the chart ships that block dormant, so the\n"
    "# sidecar turns on and learns its realm in the same edit."
)

_CHART = """apiVersion: v2
name: <app>
description: <env> environment pin for <app> (ADR-025 deploy branch).
type: application
version: <chart-version>
dependencies:
  - name: <app>
    version: <chart-version>
    repository: oci://<registry>/charts
"""


def render_deploy_branch(
    *,
    app: str,
    registry: str,
    components: tuple[str, ...],
    chart_version: str,
    image_tags: dict[str, str],
    zone: str,
    environments: tuple[str, ...],
) -> tuple[tuple[str, str], ...]:
    """The env-config files, in deploy_branch_file_order(environments).

    ``image_tags`` maps each released package name (``<app>`` for the
    single-image shape, ``<app>-<component>`` otherwise) to the tag the
    branch seeds; Image Updater advances the entry environment's tags from
    there, the chart pin stays a manual bump. ``zone`` is the install's own
    DNS zone, which fixes the rendered hostname; ``environments`` is the
    install's declared list, one folder each; ``registry`` is the install's
    ``<host>/<owner>`` prefix (ADR-044, #164), which prefixes every image
    repository and the chart's OCI home.
    """
    if not chart_version:
        raise ValueError(f"cannot render the deploy branch for {app!r}: no chart version")
    if not registry:
        raise ValueError(f"cannot render the deploy branch for {app!r}: no registry")
    if not zone:
        raise ValueError(f"cannot render the deploy branch for {app!r}: no install zone")
    if not environments:
        raise ValueError(f"cannot render the deploy branch for {app!r}: no environments")
    values_lines = [_VALUES_HEADER, f"{app}:", f"  host: {app}.{zone}"]
    if not components:
        tag = image_tags.get(app)
        if not tag:
            raise ValueError(f"cannot render the deploy branch for {app!r}: no tag for {app!r}")
        values_lines += [
            "  image:",
            f"    repository: {registry}/{app}",
            f"    tag: {tag}",
        ]
    else:
        values_lines.append("  images:")
        for component in components:
            package = f"{app}-{component}"
            tag = image_tags.get(package)
            if not tag:
                raise ValueError(
                    f"cannot render the deploy branch for {app!r}: no tag for {package!r}"
                )
            values_lines += [
                f"    {component}:",
                f"      repository: {registry}/{package}",
                f"      tag: {tag}",
            ]
    values = "\n".join(values_lines) + "\n"
    rendered: list[tuple[str, str]] = []
    for path in deploy_branch_file_order(environments):
        env = path.split("/", 1)[0]
        if path.endswith("Chart.yaml"):
            text = (
                _CHART.replace("<app>", app)
                .replace("<env>", env)
                .replace("<chart-version>", chart_version)
                .replace("<registry>", registry)
            )
        else:
            text = values
        rendered.append((path, text))
    return tuple(rendered)
