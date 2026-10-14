"""Render an app's team-folder skeleton from the studio's canonical templates.

The skeleton (namespace, Gateway, namespace-scoped RBAC, the GitOps Application,
the docs HTTPRoute) is rendered from the studio-owned templates below, keyed on
the install's own facts, the ones read off the branch the studio serves: its zone
(the hostname suffix), its Cloudflare tunnel id (the external-dns target), its
operators (the RBAC subjects), and its name (the ``deploy-<install>`` branch the
Application tracks). It is NOT copied from a donor app.

A string-mirror of a neighbour's folder cannot produce a value the neighbour does
not itself carry: most sharply the Application's ``targetRevision: deploy-<install>``,
which is this install's, not the donor's. It also silently inherits whatever the
donor happens to have (a stale annotation, an auth block a public app must not
carry). Templating removes both failure modes: every install-specific value comes
from the branch, nothing is hardcoded here, and the platform's conformance suite
gates whatever this renders. This is the skeleton counterpart of the canonical
database and identity grant templates (``database_grant`` / ``identity_grant``);
together they mean no part of a team folder is a copy of another app.
"""

# The embedded YAML template lines (the prometheus widget queries) legitimately
# exceed the line length; disable E501 for this file (the Python stays within it).
# ruff: noqa: E501

from __future__ import annotations

import re

from studio.domain.services.image_promotion import image_updater_annotation_lines
from studio.domain.services.yaml_scalar import yaml_quoted

__all__ = ["APP_REPO_ORG", "SKELETON_FILE_ORDER", "docs_service_name", "render_team_skeleton"]

# The fleet default the studio was built for: the GitHub organisation an
# install's app repos live under when its branch declares none. An install
# names its own with githubOrgUrl in values.yaml (read as InstallOrganisation,
# the same shape as the registry fact): a fleet that forks the platform into
# another organisation renders that organisation into every repoURL, GHCR
# owner, and scaffolded CI caller, and this constant is never consulted.
# Public: the use cases fall back to it through InstallOrganisation.org_or.
APP_REPO_ORG = "foundryRB"
_APP_REPO_ORG = APP_REPO_ORG

# The order the skeleton files are written (apply-read order, deterministic).
SKELETON_FILE_ORDER = (
    "namespace.yaml",
    "gateway.yaml",
    "rbac.yaml",
    "application.yaml",
    "routes.yaml",
)

_NAMESPACE = """apiVersion: v1
kind: Namespace
metadata:
  name: <app>
  labels:
    app.kubernetes.io/part-of: foundry-platform
    gateway-access: "true"          # may attach routes to shared platform Gateways (e.g. the docs portal); platform ADR-013 step 2
"""

_GATEWAY = """# Per-app Gateway, one per onboarded app. external-dns publishes <app>.<zone>
# from the target annotation below (the install's Cloudflare tunnel). Whether the
# app gates its routes behind auth is the app's OWN decision, declared in its
# k8s/values.yaml (auth.existingSecret); this Gateway only routes.
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: <app>
  namespace: network
  annotations:
    external-dns.alpha.kubernetes.io/target: <tunnel-id>.cfargotunnel.com
spec:
  gatewayClassName: traefik
  listeners:
    - name: web
      protocol: HTTP
      port: 8000
      hostname: <app>.<zone>
      allowedRoutes:
        namespaces:
          from: Selector
          selector:
            matchLabels:
              kubernetes.io/metadata.name: <app>
"""

_RBAC = """apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: <app>-team-edit
  namespace: <app>
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: edit
subjects:
<subjects>
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: httproute-editor
  namespace: <app>
rules:
  - apiGroups: ["gateway.networking.k8s.io"]
    resources: ["httproutes"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: <app>-team-httproutes
  namespace: <app>
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: httproute-editor
subjects:
<subjects>
"""

_APPLICATION = """# ArgoCD Application: the platform-owned, frozen POINTER that delivers this app
# (platform ADR-022). targetRevision is a branch and pins no version; the team owns the
# image tag + chart version in their config repo. Created once at onboarding,
# then not touched. Points at the team's per-install deploy branch (platform ADR-025): the
# app code repo, targetRevision: deploy-<install>, path: the install's entry
# environment. That environment's config lives on the orphan branch and pins the
# published chart from GHCR.
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: <app>
  namespace: argocd
  annotations:
    # ArgoCD Image Updater deploys each released image at its newest SemVer by
    # git-writing the tag into the entry environment's values (platform ADR-022): one
    # alias per image the app releases, each bound to the values path the chart
    # reads. Deployment is automatic exactly here; every other environment is
    # manual, written only by promotion. Chart-version changes remain a manual
    # pin (Image Updater only moves image tags). Write-back reuses ArgoCD's
    # repo PAT (argocd/github-creds).
<image-updater-annotations>
    argocd-image-updater.argoproj.io/write-back-method: git:secret:argocd/github-creds
    argocd-image-updater.argoproj.io/git-branch: deploy-<install>
    argocd-image-updater.argoproj.io/write-back-target: helmvalues:/<entry-env>/values.yaml
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: apps
  source:
    repoURL: https://github.com/<org>/<repo>
    targetRevision: deploy-<install>
    path: <entry-env>
  destination:
    server: https://kubernetes.default.svc
    namespace: <app>
  syncPolicy:
    automated:
      selfHeal: true
      prune: true
"""

_ROUTES = """# Docs route for the central portal (platform ADR-023): docs.<zone>/apps/<app> -> this
# app's docs Service, <docs-service> (svc- prefixed for a digit-leading app name:
# Service names are DNS-1035 labels, so they must start with a letter).
# The docs/ container is built like any other image (CI);
# until it exists this route has no backend yet. The app's docs site builds with
# astro base=/apps/<app> and its image serves the built site under that prefix
# (astro output is flat), so this no-rewrite PathPrefix route resolves. Docs are
# public by design (documentation), independent of any app auth gate.
# No homepage annotations here, deliberately: the app's tile renders from its
# foundry.yaml entry inside the platform chart (the manifest is the single
# source of the tile facts), so the route only routes.
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: <app>-docs
  namespace: <app>
spec:
  parentRefs:
    - name: docs
      namespace: network
  hostnames:
    - docs.<zone>
  rules:
    - matches:
        - path:
            type: PathPrefix
            value: /apps/<app>
      backendRefs:
        - name: <docs-service>
          port: 80
"""

_TEMPLATES = {
    "namespace.yaml": _NAMESPACE,
    "gateway.yaml": _GATEWAY,
    "rbac.yaml": _RBAC,
    "application.yaml": _APPLICATION,
    "routes.yaml": _ROUTES,
}


def docs_service_name(app: str) -> str:
    """The app's docs Service name: <app>-docs, svc- prefixed for a digit-leading app.

    Service names are DNS-1035 labels (they must start with a letter), while an
    app name is a DNS label that may legally start with a digit (2ez4tv). Such an
    app's chart cannot name its docs Service <app>-docs and carries the same svc-
    prefix it already uses for its app Service, so the route's backendRef derives
    the one name the chart can actually create.
    """
    return f"svc-{app}-docs" if app[0].isdigit() else f"{app}-docs"


def _rbac_subjects(operators: tuple[str, ...]) -> str:
    """The RBAC `subjects:` block: one User item per install operator.

    Every operator gets namespace edit and HTTPRoute edit on the app; the
    subjects are the install's operators, read from the branch (not copied from
    a donor, which would grant whoever happened to own the mirrored app).
    """
    return "\n".join(
        f"  - apiGroup: rbac.authorization.k8s.io\n    kind: User\n"
        f"    name: {yaml_quoted(operator)}"
        for operator in operators
    )


def render_team_skeleton(
    *,
    app: str,
    zone: str,
    tunnel_id: str,
    install: str,
    operators: tuple[str, ...],
    entry_env: str,
    image_components: tuple[str, ...] = (),
    repo: str = "",
    registry: str = "",
    org: str = "",
) -> tuple[tuple[str, str], ...]:
    """Render the five skeleton files for ``app`` in SKELETON_FILE_ORDER.

    ``org`` is the install's GitHub organisation (its githubOrgUrl), the owner
    every rendered repoURL and GHCR package carries; empty falls back to the
    fleet default APP_REPO_ORG, the shape of a branch predating the fact.

    ``app`` is the fleet name: the namespace, the hostname label, the chart
    name, and the GHCR packages CI publishes. ``repo`` is the app's repository
    under the org, the one thing the Application's ``repoURL`` points at; it
    defaults to ``app``, which is the same string for most apps. They are
    separate facts, so an app whose repository is named differently from itself
    renders a pointer at the repository that actually holds it.

    The app's tile facts (display, description, icon) are not among the inputs:
    the manifest entry is their single source and the platform chart renders the
    tile from it (platform ADR-032), so the skeleton wires and routes, and carries no
    second copy of a fact it does not own.

    Every install-specific token is substituted from the passed-in install facts;
    a leftover ``<...>`` placeholder means a fact was missing, so the render fails
    closed rather than shipping a manifest with an unfilled hole.
    """
    missing = [
        key
        for key, value in (
            ("zone", zone),
            ("tunnel_id", tunnel_id),
            ("install", install),
            ("entry_env", entry_env),
        )
        if not value
    ]
    if missing:
        raise ValueError(
            f"cannot render the skeleton for {app!r}: the install branch is missing "
            f"{missing} (values.yaml zone/tunnelId, foundry.yaml install/environments); "
            "an empty value renders a broken manifest, so fail closed rather than ship it"
        )
    if not operators:
        raise ValueError(
            f"cannot render the RBAC skeleton for {app!r}: the install declares no "
            "operators (values.yaml operators:); an app with no team subject is wrong"
        )
    subjects = _rbac_subjects(operators)
    rendered: list[tuple[str, str]] = []
    for filename in SKELETON_FILE_ORDER:
        text = (
            _TEMPLATES[filename]
            .replace("<subjects>", subjects)
            .replace(
                "<image-updater-annotations>",
                image_updater_annotation_lines(
                    app=app,
                    registry=registry or f"ghcr.io/{(org or _APP_REPO_ORG).lower()}",
                    components=image_components,
                ),
            )
            .replace("<org>", org or _APP_REPO_ORG)
            .replace("<tunnel-id>", tunnel_id)
            .replace("<zone>", zone)
            .replace("<install>", install)
            .replace("<entry-env>", entry_env)
            .replace("<docs-service>", docs_service_name(app))
            .replace("<repo>", repo or app)
            .replace("<app>", app)
        )
        if re.search(r"<[a-z-]+>", text):
            leftover = re.search(r"<[a-z-]+>", text)
            raise ValueError(
                f"the canonical {filename} template did not fully render for {app!r}: "
                f"unfilled placeholder {leftover.group(0)!r}; the template is broken"
            )
        rendered.append((filename, text))
    return tuple(rendered)
