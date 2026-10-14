# syntax=docker/dockerfile:1
# Build the Starlight docs site to static HTML, then serve it. The central docs
# portal mounts this site at docs.<domain>/apps/platform-studio via a no-rewrite
# PathPrefix route, so the site must both BUILD and be SERVED under that prefix:
#   - astro `base` (from DOCS_BASE) prefixes every asset + nav URL with the prefix
#   - the runtime stage serves the built files UNDER html/<prefix>, because astro's
#     output is flat (`base` rewrites URLs, it does not relocate files on disk), so
#     the no-rewrite route's /apps/platform-studio/... requests map to real files.
# DOCS_BASE defaults to / for a standalone/local build (serves at the root).
FROM node:22-slim AS build
ARG DOCS_BASE=/
WORKDIR /app
COPY package.json package-lock.json ./
# @psa-department-of-engineering/* resolves from the public npm registry
# (csd-library ADR-0003), so this needs no .npmrc, no build secret, and no
# credential of any kind (INT-FOUNDRY-039).
RUN npm ci
COPY . .
ENV DOCS_BASE=${DOCS_BASE}
RUN npm run build

FROM nginx:1.27-alpine AS runtime
ARG DOCS_BASE=/
COPY --from=build /app/dist /usr/share/nginx/html${DOCS_BASE}
EXPOSE 80
