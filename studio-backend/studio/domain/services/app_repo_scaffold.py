"""Render a new app repo's walking-skeleton scaffold from canonical templates.

The scaffold IS the REF-Foundry app-repo contract, rendered: every file the
shared ci workflow's conformance job checks for is here in the shape the
checks demand (the thin CI caller, the compose naming the released images,
the chart with the pull secret, the paused wiring, the own-Gateway route,
the docs site honoring DOCS_BASE, the commit-msg hook, the intent stubs), so
a repo born from this template is green in its own CI from the first push
and onboardable the moment its artifacts publish. The app itself is a
walking skeleton (a static landing page) the team replaces; the contract
files around it are the point.

Two-image shape by default: the app image (``<app>-app``, the compose's one
build service) and the docs image (``<app>-docs``, from docs/Dockerfile), so
the onboarding declaration for a scaffolded repo is ``["app", "docs"]``.
"""

from __future__ import annotations

import json
import re
from html import escape

from studio.domain.services.docs_scaffold_source import DOCS_SIDEBAR, OVERVIEW_TEMPLATE
from studio.domain.services.promotion_contract import render_promotion_contract
from studio.domain.services.team_skeleton import APP_REPO_ORG, docs_service_name
from studio.domain.services.yaml_scalar import yaml_quoted

__all__ = ["SCAFFOLD_COMPONENTS", "render_app_repo_scaffold"]

# The image components a scaffolded repo releases; the onboarding declaration.
SCAFFOLD_COMPONENTS: tuple[str, ...] = ("app", "docs")

# The placeholders the templates below carry. The caller's own words (the
# display name, the description) appear once per target syntax, because a
# string that is prose in a README is a scalar in YAML, a literal in
# JavaScript, and a text node in HTML, and only the prose form is itself.
_TOKEN = re.compile(
    r"<(app|APP-UPPER|org|ci-repo|registry|pull-secrets|docs-service"
    r"|display-yaml|display-js|display-html|display"
    r"|description-yaml|description-html|description|docs-sidebar)>"
)

_BUILD_YML = """# <app> CI: a thin caller of the platform's reusable build workflow.
# The build logic lives once in <org>/<ci-repo>; this only points at it, so it
# cannot drift (INT-FOUNDRY-013). Defaults apply: image names from the compose
# services, docs base = /apps/<app>.
#
# app-name is passed rather than defaulted. The shared workflow defaults it to the
# REPOSITORY name, and the app's fleet name is a separate fact (INT-SKELETON-001):
# every platform artifact this build is judged against - the Gateway, keycloak-<app>,
# pg-app-<app> - is keyed on the fleet name, and so is every package it publishes.
# On a fleet whose repositories carry a prefix the two differ, and an inherited
# default fails the conformance gate on its own chart and publishes packages the
# deploy branch does not watch.
name: build

on:
    push:
        branches: [main]
    # A fork's PR runs here too: the shared workflow's release job is guarded on
    # github.event_name, so a PR gets the conformance gate and publishes nothing.
    pull_request:

jobs:
    build:
        uses: <org>/<ci-repo>/.github/workflows/build.yml@main
        with:
            app-name: <app>
        permissions:
            contents: write
            packages: write
        secrets: inherit
"""

_TEST_YML = """# <app> app-owned test suites. Deliberately NOT a thin caller: build.yml is shared
# because release and publish must not drift, but a test suite is genuinely per-app
# (a pytest, a vitest, a Playwright e2e), so there is nothing to share. What IS
# contract is that this file exists and runs on pull_request, so a contributor's PR
# - including one from a fork - meets a gate before it is merged (INT-FOUNDRY-063).
#
# Scaffolded with the intent audit plus a runner for each suite the scaffold
# ships (the walking skeleton's pytest suite, the docs site's vitest meta-test):
# the audit only checks a marker names each active claim, so without the runners
# the claims ship "attested" by tests nothing ever executes (#21). Grow the jobs
# with the app; do not delete this file to make a red check go away.
name: test

on:
    push:
        branches: [main]
    pull_request:

jobs:
    intent:
        # A fork has no access to this org's ARC scale set, so its jobs would queue
        # forever; a fork falls back to a GitHub-hosted runner while our runs stay on
        # ARC (foundry-platform ADR-037 governs our runs, not a fork's).
        runs-on: ${{ github.event.repository.fork && 'ubuntu-latest' || 'arc-dind' }}
        steps:
            - uses: actions/checkout@v4
            - uses: actions/setup-python@v5
              with:
                  python-version: "3.13"
            # csd-intent audits intent.yaml against CSD-INTENT-01 and checks every
            # active claim but an llm one is attested by a test marker naming it.
            - name: Install the intent auditor
              run: pip install "csd-intent~=0.6.0"
            - name: Audit intent.yaml
              run: csd-intent .

    pytest:
        # The walking skeleton's own suite (tests/), the one attesting
        # INT-<APP-UPPER>-001: the audit above proves the marker exists, this
        # run is what makes the claim true.
        runs-on: ${{ github.event.repository.fork && 'ubuntu-latest' || 'arc-dind' }}
        steps:
            - uses: actions/checkout@v4
            - uses: actions/setup-python@v5
              with:
                  python-version: "3.13"
            - name: Install the intent runtime
              run: pip install "csd-pytest-intent~=0.3.0"
            - name: Run the suite
              run: pytest tests

    docs:
        # The docs site's vitest meta-test (docs/tests/), attesting
        # INT-STARLIGHT-001. npm install, not ci: the scaffold ships no
        # lockfile (the app's first docs change creates it).
        runs-on: ${{ github.event.repository.fork && 'ubuntu-latest' || 'arc-dind' }}
        steps:
            - uses: actions/checkout@v4
            - uses: actions/setup-node@v4
              with:
                  node-version: "22"
            - run: npm install --no-audit --no-fund
              working-directory: docs
            - run: npm test
              working-directory: docs
"""

_DEVOPS_DOCKERFILE = """# The app image (<app>-app): the walking skeleton serves a static landing
# page from nginx; replace the content (and this Dockerfile) as the app grows.
FROM nginx:1.27-alpine
COPY app/index.html /usr/share/nginx/html/index.html
"""

_COMPOSE = """# The repo's single source of truth for the images CI releases: every
# service with a build: section publishes, named by its image: basename
# (INT-FOUNDRY-061; the docs image publishes beside them from docs/Dockerfile).
services:
    app:
        build:
            context: ..
            dockerfile: devops/Dockerfile
        image: <app>-app:latest
        ports:
            - "8080:80"
"""

_INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title><display-html></title></head>
<body>
<h1><display-html></h1>
<p><description-html></p>
<p>Walking skeleton: replace me.</p>
</body>
</html>
"""

_CHART_YAML = """apiVersion: v2
name: <app>
description: <description-yaml>
type: application
version: 0.1.0
"""

_VALUES_YAML = """# Chart defaults. The deploy-<install> branch nests these under `<app>:` (the
# chart ships as a dependency) and pins the served tags; Image Updater
# advances them there (platform ADR-022). `host` is per install: the hostname lands
# in the deploy branch's values (install-agnostic chart, INT-FOUNDRY-046).
paused: false
host: ""
gateway:
    name: <app>
    namespace: network
imagePullSecrets:<pull-secrets>
images:
    app:
        repository: <registry>/<app>-app
        tag: latest
    docs:
        repository: <registry>/<app>-docs
        tag: latest

# Capability wiring. Flip `enabled` once the matching grant exists; the Secret
# and key names below are the ones the grant's Jobs create.
auth:
    oidc:
        # foundry-onboard-keycloak. The sidecar reads clientSecret/cookieSecret
        # out of this Secret; map them key by key onto OAUTH2_PROXY_CLIENT_SECRET
        # and OAUTH2_PROXY_COOKIE_SECRET, never with envFrom, whose variable
        # names would be the Secret's keys rather than the ones the proxy reads.
        enabled: false
        existingSecret: keycloak-<app>
        clientId: <app>
        issuer: ""
    proxyImage: quay.io/oauth2-proxy/oauth2-proxy:v7.15.5
database:
    # foundry-onboard-database. `host` is the shared cluster's read-write
    # service; the per-app role password is under key `password`.
    enabled: false
    host: shared-rw.databases.svc.cluster.local
    port: 5432
    name: <app>
    existingSecret: pg-app-<app>
events:
    # foundry-onboard-events. Two Secrets, because the grant keeps the private
    # half home: `nats-<app>` (key `seed`) is the keypair this app's own
    # generator minted in this namespace, never reflected anywhere;
    # `nats-jwt-<app>` (key `user.jwt`) is the user JWT the platform signed for
    # its public half and reflected back. The deployment assembles the two
    # into the one credentials file a NATS client reads. `servers` is the
    # bus's in-cluster address; it has no public one.
    enabled: false
    servers: nats://nats.messaging.svc.cluster.local:4222
    seedSecret: nats-<app>
    jwtSecret: nats-jwt-<app>
"""

_APP_DEPLOYMENT = """apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .Chart.Name }}
  labels:
    app.kubernetes.io/name: {{ .Chart.Name }}
spec:
  # The platform pauses an app by overriding .Values.paused on its ArgoCD
  # Application (platform ADR-030); docs stay served, this workload scales to zero.
  replicas: {{ if .Values.paused }}0{{ else }}1{{ end }}
  selector:
    matchLabels:
      app.kubernetes.io/name: {{ .Chart.Name }}
  template:
    metadata:
      labels:
        app.kubernetes.io/name: {{ .Chart.Name }}
    spec:
      imagePullSecrets:
        {{- toYaml .Values.imagePullSecrets | nindent 8 }}
      {{- if .Values.events.enabled }}
      initContainers:
        # A NATS client reads one credentials file; the grant delivers its two
        # halves as two Secrets, because reflecting them together would have
        # carried the private seed out of this namespace. Assembling them here
        # keeps that boundary and costs one short init step. Uses the app's own
        # image so the pod pulls nothing extra.
        - name: assemble-nats-creds
          image: "{{ .Values.images.app.repository }}:{{ .Values.images.app.tag }}"
          command:
            - /bin/sh
            - -c
            - |
              set -eu
              # Built line by line rather than with one printf: a credentials file is
              # framed text, and $(cat ...) normalises whatever trailing newline each
              # Secret happens to carry.
              {
                echo '-----BEGIN NATS USER JWT-----'
                echo "$(cat /jwt/user.jwt)"
                echo '------END NATS USER JWT------'
                echo
                echo '-----BEGIN USER NKEY SEED-----'
                echo "$(cat /seed/seed)"
                echo '------END USER NKEY SEED------'
              } > /out/app.creds
              chmod 400 /out/app.creds
              echo "assembled the bus credentials"
          volumeMounts:
            - { name: nats-seed, mountPath: /seed, readOnly: true }
            - { name: nats-jwt, mountPath: /jwt, readOnly: true }
            - { name: nats-creds, mountPath: /out }
      {{- end }}
      containers:
        - name: app
          image: "{{ .Values.images.app.repository }}:{{ .Values.images.app.tag }}"
          ports:
            - containerPort: 80
          {{- if .Values.events.enabled }}
          env:
            - name: NATS_URL
              value: {{ .Values.events.servers | quote }}
            - name: NATS_CREDS
              value: /var/run/nats/app.creds
          volumeMounts:
            - name: nats-creds
              mountPath: /var/run/nats
              readOnly: true
          {{- end }}
      {{- if .Values.events.enabled }}
      # Neither Secret is optional: a missing grant holds the pod at
      # CreateContainerConfigError, where the absent Secret is named, rather
      # than starting it with an empty credentials file that drops every
      # publish silently (the one-way rule makes that failure mute by design).
      volumes:
        - name: nats-seed
          secret:
            secretName: {{ required "set events.seedSecret" .Values.events.seedSecret }}
        - name: nats-jwt
          secret:
            secretName: {{ required "set events.jwtSecret" .Values.events.jwtSecret }}
        - name: nats-creds
          emptyDir: {}
      {{- end }}
"""

_APP_SERVICE = """apiVersion: v1
kind: Service
metadata:
  name: {{ .Chart.Name }}
spec:
  selector:
    app.kubernetes.io/name: {{ .Chart.Name }}
  ports:
    - port: 80
      targetPort: 80
"""

_APP_ROUTE = """{{- if .Values.host }}
# external-dns registers DNS from this route's hostname; the parent is the
# app's OWN Gateway in the network namespace, never an invented or platform
# one (INT-FOUNDRY-046). host is set per install on the deploy branch.
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: {{ .Chart.Name }}
spec:
  parentRefs:
    - name: {{ .Chart.Name }}
      namespace: {{ .Values.gateway.namespace }}
  hostnames:
    - {{ .Values.host }}
  rules:
    - backendRefs:
        - name: {{ .Chart.Name }}
          port: 80
{{- end }}
"""

_DOCS_DEPLOYMENT = """apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .Chart.Name }}-docs
  labels:
    app.kubernetes.io/component: docs
spec:
  replicas: 1
  selector:
    matchLabels:
      # Inline on purpose: the homepage tile derives its pod selector from the
      # <app>-docs route name (INT-FOUNDRY-048); the shared name helper would
      # yield the bare chart name and the tile would render NOT FOUND.
      app.kubernetes.io/name: {{ .Chart.Name }}-docs
  template:
    metadata:
      labels:
        app.kubernetes.io/name: {{ .Chart.Name }}-docs
        app.kubernetes.io/component: docs
    spec:
      imagePullSecrets:
        {{- toYaml .Values.imagePullSecrets | nindent 8 }}
      containers:
        - name: docs
          image: "{{ .Values.images.docs.repository }}:{{ .Values.images.docs.tag }}"
          ports:
            - containerPort: 80
"""

_DOCS_SERVICE = """apiVersion: v1
kind: Service
metadata:
  # The platform's docs HTTPRoute targets the DERIVED backendRef (svc- prefix
  # exactly when the chart name leads with a digit, INT-FOUNDRY-056), so the
  # name is rendered literally here rather than templated.
  name: <docs-service>
  labels:
    app.kubernetes.io/component: docs
spec:
  selector:
    app.kubernetes.io/name: {{ .Chart.Name }}-docs
  ports:
    - port: 80
      targetPort: 80
"""

_DOCS_PACKAGE_JSON = """{
    "name": "<app>-docs",
    "private": true,
    "type": "module",
    "scripts": {
        "dev": "astro dev",
        "build": "astro build",
        "test": "vitest run"
    },
    "dependencies": {
        "@astrojs/starlight": "^0.42.5",
        "astro": "^7.2.10",
        "astro-mermaid": "^2.0.2",
        "mermaid": "^11.16.1",
        "@psa-department-of-engineering/starlight-theme": "^1.2.0"
    },
    "devDependencies": {
        "@psa-department-of-engineering/vitest-intent": "^2.0.1",
        "vitest": "^5.0.3"
    }
}
"""

_DOCS_ASTRO_CONFIG = """import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import mermaid from 'astro-mermaid';
import { mermaidConfig } from '@psa-department-of-engineering/starlight-theme';

// base derives from DOCS_BASE so the site mounts under the portal prefix
// (/apps/<app>); the Dockerfile places the built files under the same prefix
// because Astro's output is flat (INT-FOUNDRY-018, platform ADR-023).
export default defineConfig({
    base: process.env.DOCS_BASE || '/',
    integrations: [
        mermaid({ autoTheme: true, mermaidConfig }),
        starlight({
            title: <display-js>,
            customCss: ['@psa-department-of-engineering/starlight-theme/styles.css'],
            sidebar: [
<docs-sidebar>            ],
        }),
    ],
});
"""

_DOCS_CONTENT_CONFIG = """import { defineCollection } from 'astro:content';
import { z } from 'astro/zod';
import { docsLoader } from '@astrojs/starlight/loaders';
import { docsSchema } from '@astrojs/starlight/schema';

// The fleet's doc frontmatter (id, type, status, summary, updated) rides on
// the Starlight schema; type: is what the app-contract check reads
// (INT-FOUNDRY-010).
export const collections = {
    docs: defineCollection({
        loader: docsLoader(),
        schema: docsSchema({
            extend: z.object({
                id: z.string().optional(),
                type: z.string().optional(),
                status: z.string().optional(),
                summary: z.string().optional(),
                updated: z.string().optional(),
            }),
        }),
    }),
};
"""

_DOCS_DOCKERFILE = """# syntax=docker/dockerfile:1
# The docs image (<app>-docs): built like any other image (CI), served by
# nginx under DOCS_BASE so the portal's no-rewrite route resolves
# (INT-FOUNDRY-018).
FROM node:22-alpine AS build
ARG DOCS_BASE=/
WORKDIR /app
COPY package*.json ./
# The lock, once the app commits one, is the tree the docs test job installs.
# @psa-department-of-engineering/* resolves from the public npm registry
# (csd-library ADR-0003), so this needs no .npmrc, no build secret, and no
# credential of any kind (INT-FOUNDRY-039).
RUN npm install --no-audit --no-fund
COPY . .
ENV DOCS_BASE=${DOCS_BASE}
RUN npm run build

FROM nginx:1.27-alpine
ARG DOCS_BASE=/
COPY --from=build /app/dist /usr/share/nginx/html${DOCS_BASE}
"""

def _docs_overview() -> str:
    """Fill the canonical Overview with the served walking skeleton's topology."""
    front, body = OVERVIEW_TEMPLATE.split("\n---\n", 1)
    values = {
        "title": "<display-yaml>",
        "id": "DOC-OVERVIEW-001",
        "status": "Active",
        "updated": '\"2026-10-04\"',
        "summary": "<description-yaml>",
    }
    for key, value in values.items():
        front = re.sub(
            rf"^{key}:.*$", lambda match, key=key, value=value: f"{key}: {value}",
            front, flags=re.MULTILINE,
        )
    body = re.sub(r"<!--[\s\S]*?-->\s*", "", body)
    body = body.replace(
        "<one-paragraph intro: what this is and how the parts fit together>", "<description>"
    )
    body = body.replace("  %% the topology; group nodes so the picture matches the prose below",
        '  subgraph client [Reader]\n    browser["Browser"]\n  end\n'
        '  subgraph served [Released images]\n    app["Application landing page"]\n'
        '    docs["Documentation site"]\n  end\n  browser --> app\n  browser --> docs')
    body = re.sub(r"^- \*\*<aspect>.*$", "", body, flags=re.M)
    body = body.replace(
        "- [<next page>](<path>) <one line on why>",
        "- [Run the application](http://localhost:8080/): open the local landing page "
        "after starting Docker Compose.",
    )
    return front + "\n---\n" + body


_DOCS_INDEX = _docs_overview()

_DOCS_INTENT = """# The docs site's own CSD-INTENT-01 claims (INT-FOUNDRY-022). The STARLIGHT
# bundle's first claim is the floor, carried here with the bundle's own wording
# so the bundle merges over it as a no-op; tests/frontmatter.test.ts attests it.
#
# To take the whole bundle (eleven claims over frontmatter, the content
# collection and page structure): delete tests/frontmatter.test.ts, then run
# apply-intent-bundle --bundle starlight --target docs. The bundle's spec lands
# at tests/starlight.test.ts carrying a marker for every claim it adds. Its
# structural claims (id, status and updated frontmatter, intro prose, a level-2
# heading on every page) hold against the pages that describe the delivered application.
INT-STARLIGHT-001:
    version: 1.0.0
    status: active
    statement: "Every doc page MUST have a non-empty `title` frontmatter field."
    rationale: "Starlight uses title for nav, page heading, and OG metadata; missing
        title yields broken UI."
    test:
        scope: unit
        component: ContentCollection
        type: invariant
    criticality: critical
"""

_ROOT_INTENT = """# The app's own CSD-INTENT-01 claims (INT-FOUNDRY-009). One claim is the
# floor; grow this file with the app.
INT-<APP-UPPER>-001:
    version: 1.0.0
    status: active
    statement: "The app serves its landing page at the root path."
    rationale: "The walking skeleton ships serving from day one."
    test:
        scope: integration
        component: WalkingSkeleton
        type: invariant
    criticality: medium
"""

_ROOT_INTENT_TEST = '''"""The walking skeleton's claim, attested.

A claim with no test is not a claim: csd-intent fails an unattested one, and
the shared workflow's conformance job runs that audit, so a scaffold shipping
intent.yaml without this file is red on its own first push. Grow this suite
with the app - the claim is the floor, not the ceiling.
"""

from pathlib import Path

from pytest_intent import intent

_REPO = Path(__file__).resolve().parents[1]


@intent("INT-<APP-UPPER>-001")
def test_the_landing_page_is_served_at_the_root_path() -> None:
    page = _REPO / "app" / "index.html"
    assert page.is_file(), "the walking skeleton serves app/index.html"
    assert "<html" in page.read_text(encoding="utf-8").lower()
    # Serving it at / is the image's doing: nginx roots on this exact document,
    # so the claim holds only while the Dockerfile still puts it there.
    dockerfile = (_REPO / "devops" / "Dockerfile").read_text(encoding="utf-8")
    assert "app/index.html" in dockerfile
    assert "/usr/share/nginx/html/index.html" in dockerfile
'''

_DOCS_VITEST_CONFIG = """import { defineConfig } from 'vitest/config';

export default defineConfig({
    test: {
        include: ['tests/**/*.test.ts'],
        environment: 'node',
    },
});
"""

_DOCS_FRONTMATTER_TEST = """/**
 * The STARLIGHT bundle's first claim, attested (INT-FOUNDRY-022).
 *
 * The bundle is the claim AND the spec that holds it; shipping
 * docs/intent.yaml alone leaves an unattested claim, which csd-intent fails in
 * the shared workflow's conformance job. Walks the docs tree, parses each
 * page's frontmatter, and asserts the title: every page must carry one.
 */

import { readdirSync, readFileSync, statSync } from 'node:fs';
import { extname, join, relative } from 'node:path';

import { expect } from 'vitest';

import { intent } from '@psa-department-of-engineering/vitest-intent';

const DOCS_DIR = join(process.cwd(), 'src', 'content', 'docs');
const FRONTMATTER_RE = /^---\\s*\\n([\\s\\S]*?)\\n---/;

function pages(dir: string): string[] {
    return readdirSync(dir).flatMap((entry) => {
        const full = join(dir, entry);
        if (statSync(full).isDirectory()) return pages(full);
        return ['.md', '.mdx'].includes(extname(full)) ? [full] : [];
    });
}

intent('INT-STARLIGHT-001', 'every doc page has a non-empty title', () => {
    const found = pages(DOCS_DIR);
    expect(found.length).toBeGreaterThan(0);
    for (const page of found) {
        const match = FRONTMATTER_RE.exec(readFileSync(page, 'utf8'));
        const where = relative(DOCS_DIR, page);
        expect(match, `${where}: no frontmatter block`).not.toBeNull();
        expect(match![1], `${where}: frontmatter carries no title:`).toMatch(/^title:\\s*\\S+/m);
    }
});
"""

# The local half of ci's check-commit-hygiene: both commit-message invariants
# that gate enforces, rendered as commit-msg hooks. The gate stays the single
# source of the rules; the rendered header below carries the reasoning, since
# the committer who trips a hook is the one who needs it.
_PRE_COMMIT = """# The platform's commit convention, checked at commit time so a violation
# fails the commit instead of the push. The convention is documented on the
# platform portal's GitOps delivery page, under "Commit convention"; CI's
# commit-hygiene job is the check that holds, and this config is a conformance
# claim (INT-FOUNDRY-019). pygrep is pre-commit's own built-in matcher, so the
# trailer check needs no toolchain the committer may not have.
#
# Install once per clone: pre-commit install. Both hooks run at commit-msg, and
# `pre-commit install` wires the pre-commit stage ONLY - so without the line
# below it writes .git/hooks/pre-commit, git never calls either hook, and both
# guards sit inert while the config looks complete.
default_install_hook_types: [commit-msg]
repos:
    - repo: https://github.com/compilerla/conventional-pre-commit
      rev: v3.4.0
      hooks:
          - id: conventional-pre-commit
            stages: [commit-msg]
    - repo: local
      hooks:
          - id: no-co-authored-by
            name: no Co-authored-by trailer
            entry: '^[ \\t\\v\\f]*Co-authored-by:'
            language: pygrep
            args: [--ignore-case]
            stages: [commit-msg]
"""

_ENV_EXAMPLE = """# Environment the app reads (INT-FOUNDRY-008). The walking skeleton reads
# none; document each variable here as the app grows.
"""

# Born ignoring what the repo's own tooling generates. Without this file the
# artifacts are untracked-and-not-ignored, so the first `git add -A` commits
# docs/node_modules/ wholesale - which is exactly how it went in every repo
# scaffolded before this template existed, each one patched by a different
# hand afterwards and none of them the same. The two build trees are the
# whole point: `npm install` in docs/ writes node_modules/, and `astro build`
# writes dist/ and .astro/ beside it.
_GITIGNORE = """# Python (tests/)
__pycache__/
*.py[cod]
*.egg-info/
.pytest_cache/
.venv/
venv/

# Node (docs/)
node_modules/
dist/
.astro/
coverage/

# Environment (out-of-band secrets: a committed *.env is never real)
.env
k8s/secrets/*.env
"""

_README = """# <display>

<description>

Scaffolded by platform-studio (create_app_repo): a walking skeleton carrying
the full REF-Foundry app-repo contract, green in CI from the first push.

## Run with Docker

```bash
docker compose -f devops/docker-compose.yml up --build
```

The app serves at http://localhost:8080.

## Develop without Docker

The walking skeleton is a static page (`app/index.html`); open it directly,
or serve the docs site with `cd docs && npm install && npm run dev`. Replace
this section as the real app takes shape.

## Layout

- `app/` - the application (walking skeleton: a static landing page)
- `devops/` - Dockerfile + compose (the released images) + the promotion contract
- `k8s/` - the Helm chart CI publishes (paused wiring, pull secret, own-Gateway route)
- `docs/` - the Starlight docs site, served under the portal at `/apps/<app>`
- `intent.yaml` - the app's CSD-INTENT-01 claims
- `.github/workflows/build.yml` - thin caller of the shared ci workflow

## Commits

Every commit follows the platform's commit convention: a Conventional Commit
subject and no co-author trailer. CI derives the version from the type and
blocks release otherwise. The convention is documented on the platform
portal's GitOps delivery page, under "Commit convention"; the committed
`.pre-commit-config.yaml` checks it locally once installed (`pre-commit install`).
"""


def _js_string(value: str) -> str:
    """``value`` as a JavaScript string literal; a JSON literal is one."""
    return json.dumps(value, ensure_ascii=False)


def render_app_repo_scaffold(
    *,
    app: str,
    display_name: str,
    description: str,
    registry: str,
    pull_secret: str = "ghcr-pull",
    org: str = "",
    ci_repo: str = "",
) -> dict[str, str]:
    """Every file of the walking-skeleton repo, path to text.

    ``org`` and ``ci_repo`` are the creating install's organisation fact: the
    scaffolded build caller runs ``<org>/<ci_repo>``'s shared workflow, never
    another fleet's. Empty falls back to the fleet default (APP_REPO_ORG, `ci`).

    ``registry`` is the creating install's ``<host>/<owner>`` prefix (platform ADR-044,
    #164) and ``pull_secret`` its pull-secret name: the chart's defaults belong
    to whichever install authored them, so the scaffold bakes that install's
    facts. An empty ``pull_secret`` renders ``imagePullSecrets: []``, the
    node-identity shape (pulls ride the node role, no seeded credential).
    """
    files = {
        ".github/workflows/build.yml": _BUILD_YML,
        ".github/workflows/test.yml": _TEST_YML,
        ".env.example": _ENV_EXAMPLE,
        ".gitignore": _GITIGNORE,
        ".pre-commit-config.yaml": _PRE_COMMIT,
        "README.md": _README,
        "app/index.html": _INDEX_HTML,
        "devops/Dockerfile": _DEVOPS_DOCKERFILE,
        "devops/docker-compose.yml": _COMPOSE,
        "devops/promotion.yaml": render_promotion_contract(),
        "docs/Dockerfile": _DOCS_DOCKERFILE,
        "docs/astro.config.mjs": _DOCS_ASTRO_CONFIG,
        "docs/intent.yaml": _DOCS_INTENT,
        "docs/package.json": _DOCS_PACKAGE_JSON,
        "docs/src/content.config.ts": _DOCS_CONTENT_CONFIG,
        "docs/src/content/docs/index.md": _DOCS_INDEX,
        "intent.yaml": _ROOT_INTENT,
        "tests/test_walking_skeleton.py": _ROOT_INTENT_TEST,
        "docs/vitest.config.ts": _DOCS_VITEST_CONFIG,
        "docs/tests/frontmatter.test.ts": _DOCS_FRONTMATTER_TEST,
        "k8s/Chart.yaml": _CHART_YAML,
        "k8s/values.yaml": _VALUES_YAML,
        "k8s/templates/deployment.yaml": _APP_DEPLOYMENT,
        "k8s/templates/service.yaml": _APP_SERVICE,
        "k8s/templates/httproute.yaml": _APP_ROUTE,
        "k8s/templates/docs-deployment.yaml": _DOCS_DEPLOYMENT,
        "k8s/templates/docs-service.yaml": _DOCS_SERVICE,
    }
    values = {
        "docs-sidebar": DOCS_SIDEBAR,
        "app": app,
        "APP-UPPER": app.upper(),
        "org": org or APP_REPO_ORG,
        "ci-repo": ci_repo or "ci",
        "registry": registry,
        "pull-secrets": f"\n    - name: {pull_secret}" if pull_secret else " []",
        "docs-service": docs_service_name(app),
        "display": display_name,
        "display-yaml": yaml_quoted(display_name),
        "display-js": _js_string(display_name),
        "display-html": escape(display_name, quote=False),
        "description": description,
        "description-yaml": yaml_quoted(description),
        "description-html": escape(description, quote=False),
    }
    # One pass per template: substituted text is output, never input, so a
    # caller whose own words contain a placeholder gets them back verbatim.
    return {
        path: _TOKEN.sub(lambda match: values[match.group(1)], text)
        for path, text in files.items()
    }
