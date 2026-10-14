// Refresh src/models/openapi.json from a running backend's /openapi.json.
// Override the base with API_BASE; defaults to the dev-proxy target.

import { writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, '..');
const base = (process.env.API_BASE ?? 'http://127.0.0.1:8917').replace(/\/$/, '');
const url = `${base}/openapi.json`;

const response = await fetch(url);
if (!response.ok) {
    throw new Error(`Failed to fetch ${url}: ${response.status} ${response.statusText}`);
}
const spec = await response.json();
const out = resolve(root, 'src/models/openapi.json');
writeFileSync(out, `${JSON.stringify(spec, null, 2)}\n`, 'utf8');
console.log(`Wrote ${out} from ${url}`);
