---
title: Connect an agent
id: DOC-GUIDE-CONNECT-AGENT-001
type: Guide
status: Active
updated: "2026-10-04"
summary: "Point an MCP client at the deployed studio's /mcp endpoint over HTTP Basic."
---

The deployed studio serves its MCP endpoint at `https://platform-studio.<zone>/mcp`, the zone being the install's own from the deploy branch's `zone` value. The machine door stays on fail-closed HTTP Basic even where the chart's OIDC gate fronts the human surfaces, because a machine-to-machine channel cannot complete an interactive login. Any streamable-HTTP MCP client that can send an `Authorization` header connects; the steps below use Claude Code.

## Steps

1. Base64-encode the credential as `user:password` (the values from the `platform-studio-auth` Secret):

   ```powershell
   [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("user:password"))
   ```

2. Add the server:

   ```bash
   claude mcp add --scope user --transport http platform-studio https://platform-studio.<zone>/mcp --header "Authorization: Basic <base64(user:password)>"
   ```

3. Verify: in a new Claude Code session, `/mcp` lists `platform-studio` as connected, and the `list_apps` tool returns the apps the install manifest declares.

## The onboard-app prompt

The server publishes the `onboard-app` prompt, the full onboarding runbook parametrized with live install facts. In Claude Code it surfaces as a slash command (`/mcp__platform-studio__onboard-app`); the install side ships as a PR through the studio's tools, and everything in the app's own repo the agent executes itself.

## Read next

- [Architecture](../../reference/architecture/): the full tool list and what each returns.
- [Decisions](../../decisions/): the architectural decision records.
