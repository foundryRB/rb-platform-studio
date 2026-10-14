# platform-studio

Onboarding and management studio for one Foundry install of the [platform repo](https://github.com/foundryRB/rb-platform): an install-manifest browser, conformance reports, and conformance-gated onboarding that ships every change as a pull request the platform repo's CI merges on open. One deployable serves the React SPA, the REST API under `/api`, and the MCP server under `/mcp` over one hexagonal core.

The install's deploy branch (`STUDIO_DEPLOY_BRANCH`, no default: PR-mode fails closed if unset) is the studio's datastore: cloned at runtime onto a volume, parked on that branch, read for every view, and mutated only on `onboard/<app>` branches whose pull requests base against it. An onboarding adds the app's entry to `foundry.yaml` (under its role, `parts` or `output`) and renders its `teams/<app>/` folder per concern file from the studio's canonical templates; every manifest-derived view (dashboards, homepage bookmarks, docs index) is rendered from the manifest by the platform chart, so nothing is generated into files. The gate is the install conformance checks over the candidate working tree (a baseline diff: a change may not introduce failures the deploy branch does not already have). Everything team-owned - the app repo's `deploy` branch, secrets - ships as the `onboard-app` MCP prompt the calling agent executes itself.

## Run with Docker

```bash
docker compose -f devops/docker-compose.yml up --build
```

Serves everything on <http://localhost:8000>. The compose file runs the operator-owned composition by default; set `STUDIO_PLATFORM_REPO_URL` and `STUDIO_GITHUB_TOKEN` in it for PR-mode against a real remote. Building pulls `@psa-department-of-engineering/*` packages from the public npm registry, so no credential is needed:

```powershell
docker build -f devops/Dockerfile -t platform-studio .
```

## Develop without Docker

Requires the sibling-clone topology: `foundry-platform` checked out next to this repo (or `STUDIO_PLATFORM_ROOT` pointing at a checkout) with the install's deploy branch checked out, plus Python 3.10+ and Node 22.

```powershell
powershell -ExecutionPolicy Bypass -File devops\start.ps1
```

First run provisions the backend venv (with the gates toolchain) and the frontend `node_modules` + generated API types, then spawns the backend on <http://127.0.0.1:8917> and the vite dev server on <http://localhost:5217> (proxying `/api`). The local composition writes onboardings into your working tree and opens no PRs; you review and commit yourself.

Backend tests and lint:

```powershell
cd studio-backend
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m pytest -q
```

## Layout

```text
studio-backend/    hexagonal FastAPI backend: domain, application (ports + use cases),
                   adapters (inbound http + mcp; outbound platform_fs, conformance_fs,
                   git_cli / git_noop), container.py composition root
studio-frontend/   React MVVM SPA (vite, zustand, generated OpenAPI types)
devops/            Dockerfile (one image: SPA + /api + /mcp), compose, local launcher
k8s/               Helm chart; secrets/*.env.example templates (applied out of band)
docs/              Starlight docs site (served at docs.<domain>/apps/platform-studio)
intent.yaml        CSD intent claims attested by the test suites
```

## Doors

| Surface | Path | Notes |
| --- | --- | --- |
| SPA | `/` | install browser, conformance, PR status, onboarding wizard |
| REST | `/api` | the OpenAPI contract the SPA types generate from |
| MCP | `/mcp` | streamable HTTP; tools mirror the inbound ports, plus the `onboard-app` prompt |

The chart defaults to OIDC through oauth2-proxy for the SPA and `/api`. HTTP Basic (`STUDIO_AUTH_USER` / `STUDIO_AUTH_PASSWORD`) gates `/mcp` with `STUDIO_AUTH_SCOPE=mcp`. Standalone, the Basic gate covers all three surfaces; `/api/health` stays open for probes. Connect an agent:

```bash
claude mcp add --scope user --transport http platform-studio https://platform-studio.<zone>/mcp --header "Authorization: Basic <base64(user:password)>"
```

## Commits

Every commit follows the platform's commit convention: a Conventional Commit
subject and no co-author trailer. CI derives the version from the type and
blocks release otherwise. The convention is documented on the platform
portal's GitOps delivery page, under "Commit convention"; the committed
`.pre-commit-config.yaml` checks it locally once installed (`pre-commit install`).
