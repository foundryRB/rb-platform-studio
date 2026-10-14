import { defineConfig } from 'astro/config';
import mermaid from 'astro-mermaid';
import starlight from '@astrojs/starlight';
import { mermaidConfig } from '@psa-department-of-engineering/starlight-theme';

export default defineConfig({
  site: process.env.SITE_URL ?? 'http://localhost:4321',
  // The central docs portal mounts this site under /apps/<app>; CI passes the
  // prefix as DOCS_BASE so asset and nav URLs resolve under it. Defaults to '/'
  // for standalone/local builds.
  base: process.env.DOCS_BASE || '/',
  integrations: [
    // Must precede starlight so it transforms ```mermaid blocks before
    // expressive-code renders them as code. autoTheme follows dark/light.
    // mermaidConfig + the stylesheet come from the shared starlight-theme package
    // (one source of truth; REF-StarlightDocs 8.1).
    mermaid({ autoTheme: true, mermaidConfig }),
    starlight({
      title: 'Platform Studio',
      components: { SiteTitle: './src/components/SiteTitle.astro' },
      logo: { light: './src/assets/rb-lockup-light.svg', dark: './src/assets/rb-lockup-dark.svg', alt: 'Software Engineering, RB' },
      description: 'Onboarding and management studio for the platform repo: registry, conformance, gated onboardings as pull requests, MCP server',
      // Shared theme first, then this site's own overrides (kept minimal).
      customCss: [
        '@psa-department-of-engineering/starlight-theme/styles.css',
        './src/styles/custom.css', './src/styles/rb.css'],
      lastUpdated: true,
      tableOfContents: {
        minHeadingLevel: 2,
        maxHeadingLevel: 3,
      },
      sidebar: [
        {
          label: 'Start Here',
          items: ['index'],
        },
        {
          label: 'Reference',
          items: [{ autogenerate: { directory: 'reference' } }],
        },
        {
          label: 'Guides',
          items: [{ autogenerate: { directory: 'guides' } }],
        },
        {
          label: 'Decisions',
          items: [{ autogenerate: { directory: 'decisions' } }],
        },
      ],
    }),
  ],
});
