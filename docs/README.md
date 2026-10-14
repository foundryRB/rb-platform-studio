# Platform Studio docs

The Starlight site introduces one install's studio, its management tools, and the delivery evidence returned by app status.

## Run and verify

```bash
npm ci
npm run dev
```

The dev server serves at `http://localhost:4321`. `DOCS_BASE` selects the portal prefix for a production build.

| Command | Action |
|---|---|
| `npm run build` | Generate the decisions index, check the schema and TypeScript, and build static HTML |
| `npm run preview` | Serve the built site locally |
| `npm test` | Run the STARLIGHT, ADR, and generated-navigation checks |
| `npm run lint:md` | Lint authored Markdown |

The docs CI job runs lint, tests, and the static build.

## Author a page

Write pages under `src/content/docs/`. The collection schema in `src/content.config.ts` validates their frontmatter. Use Markdown and the page type that matches its purpose; each page carries `title`, `id`, `type`, `status`, and `updated`.

The Overview leads to the architecture, agent connection guide, live-status reference, and decisions. The sidebar groups guides and reference pages by folder. Use Mermaid for structure diagrams, with the shared theme configured in `astro.config.mjs`.

Edit ADR records in `src/content/docs/decisions/`. The build derives their navigation index from their titles and `adr_status`, so the index is generated rather than authored.

## App scaffold inputs

The app-repository scaffold projects the STARLIGHT Overview template and documentation sidebar from a pinned playbook revision. From the repository root, `python scripts/project_docs_scaffold.py --check` checks the committed runtime projection; set `GH_TOKEN` when the upstream requires authentication. To refresh the projection, update the pinned revision in the script and run it without `--check`. The optional `--source-root <checkout>` reads the same inputs from a checkout.

The generated constants carry their source revision. App creation uses them without a network or checkout dependency. The new app starts with an Overview of its served walking skeleton and sidebar groups for the pages its delivery will write.
