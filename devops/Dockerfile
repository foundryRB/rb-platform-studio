# syntax=docker/dockerfile:1

# Stage 1: build the React SPA. @psa-department-of-engineering/vitest-intent is
# on the public npm registry (csd-library ADR-0003), so this needs no .npmrc,
# no build secret, and no credential.
FROM node:22-slim AS web
WORKDIR /app/studio-frontend
COPY studio-frontend/package.json studio-frontend/package-lock.json ./
RUN npm ci
COPY studio-frontend ./
RUN npm run build

# Stage 2: runtime. One Python image serves the SPA, /api, and /mcp.
# git is a runtime dependency: the install's deploy branch is cloned onto the
# /data volume and every onboarding rides a branch into a pull request against
# it (ADR-002, ADR-009). The install conformance checks (the gate, ADR-007)
# run in-process over the working tree, so no test toolchain ships.
FROM python:3.12-slim AS runtime
WORKDIR /app
COPY --from=alpine/helm:3.17.3 /usr/bin/helm /usr/local/bin/helm
ENV PYTHONUNBUFFERED=1 \
    STUDIO_PLATFORM_ROOT=/data/platform
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
COPY studio-backend/pyproject.toml ./studio-backend/
COPY studio-backend/studio ./studio-backend/studio
RUN pip install --no-cache-dir -e "./studio-backend"
COPY --from=web /app/studio-frontend/dist ./studio-backend/web/dist
RUN mkdir -p /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health').read()" || exit 1
CMD ["python", "-m", "uvicorn", \
     "studio.adapters.inbound.http.app:create_app", \
     "--factory", "--host", "0.0.0.0", "--port", "8000"]
