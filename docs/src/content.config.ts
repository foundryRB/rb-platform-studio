import { defineCollection } from 'astro:content';
import { z } from 'astro/zod';
import { docsLoader } from '@astrojs/starlight/loaders';
import { docsSchema } from '@astrojs/starlight/schema';

// Required frontmatter per REF-StarlightDocs §4.
// Extends Starlight's docsSchema with project-specific fields.
const docs = defineCollection({
  loader: docsLoader(),
  schema: docsSchema({
    extend: z.object({
      id: z.string().regex(/^DOC-[A-Z0-9-]+$/, "id must look like DOC-FOO-001"),
      type: z.enum(['Overview', 'Guide', 'Standard', 'Reference', 'Flow']),
      status: z.enum(['Draft', 'Active', 'Deprecated']).default('Draft'),
      updated: z.string().regex(/^\d{4}-\d{2}-\d{2}$/, "updated must be YYYY-MM-DD"),
      version: z.string().optional(),
      owner: z.string().optional(),
      tags: z.array(z.string()).optional(),
      summary: z.string().optional(),
      adr_status: z.enum(['Proposed', 'Decided', 'Superseded', 'Deprecated', 'Pending']).optional(),
      supersedes: z.string().optional(),
      superseded_by: z.string().optional(),
    }),
  }),
});

export const collections = { docs };
