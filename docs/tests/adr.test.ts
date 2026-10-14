/**
 * ADR bundle - vitest implementation.
 *
 * Walks src/content/docs/decisions/ for ADR pages, parses their frontmatter,
 * and asserts each claim from intent.yaml: adr_status validity, id uniqueness,
 * and that supersede references resolve to an existing ADR.
 */

import { readdirSync, readFileSync, statSync } from "node:fs";
import { basename, extname, join } from "node:path";

import { intent } from "@psa-department-of-engineering/vitest-intent";

const DECISIONS_DIR = join(process.cwd(), "src", "content", "docs", "decisions");
const VALID_ADR_STATUSES = new Set([
  "Proposed",
  "Decided",
  "Superseded",
  "Deprecated",
  "Pending",
]);
const FRONTMATTER_RE = /^---\s*\n([\s\S]*?)\n---/;

interface Adr {
  slug: string; // filename stem, e.g. ADR-001
  frontmatter: Record<string, string>;
}

function* walkMarkdown(dir: string): Generator<string> {
  let entries: string[];
  try {
    entries = readdirSync(dir);
  } catch {
    return;
  }
  for (const name of entries) {
    const full = join(dir, name);
    let st;
    try {
      st = statSync(full);
    } catch {
      continue;
    }
    if (st.isDirectory()) {
      yield* walkMarkdown(full);
    } else if (st.isFile() && (extname(name) === ".md" || extname(name) === ".mdx")) {
      yield full;
    }
  }
}

function parseFrontmatter(text: string): Record<string, string> | null {
  const m = FRONTMATTER_RE.exec(text);
  if (!m) return null;
  const out: Record<string, string> = {};
  for (const line of m[1].split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const colon = trimmed.indexOf(":");
    if (colon === -1) continue;
    const key = trimmed.slice(0, colon).trim();
    let value = trimmed.slice(colon + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    out[key] = value;
  }
  return out;
}

function loadAdrs(): Adr[] {
  const adrs: Adr[] = [];
  for (const file of walkMarkdown(DECISIONS_DIR)) {
    // The decisions index is a navigation page, not an ADR; skip it.
    if (basename(file, extname(file)).toLowerCase() === "index") continue;
    let text: string;
    try {
      text = readFileSync(file, "utf-8");
    } catch {
      continue;
    }
    const fm = parseFrontmatter(text);
    if (fm === null) continue;
    adrs.push({ slug: basename(file, extname(file)), frontmatter: fm });
  }
  return adrs;
}

import { describe, expect } from "vitest";

describe("ADR bundle", () => {
  const adrs = loadAdrs();

  intent("INT-ADR-001", "every ADR has a valid adr_status", () => {
    const offenders = adrs
      .filter((a) => !VALID_ADR_STATUSES.has(a.frontmatter["adr_status"]))
      .map((a) => `${a.slug} (adr_status=${a.frontmatter["adr_status"]})`);
    expect(offenders, `ADRs with invalid adr_status: ${offenders.join(", ")}`).toEqual([]);
  });

  intent("INT-ADR-002", "ADR ids are unique across the decisions collection", () => {
    const ids = new Map<string, string[]>();
    for (const a of adrs) {
      const id = a.frontmatter["id"];
      if (!id) continue;
      if (!ids.has(id)) ids.set(id, []);
      ids.get(id)!.push(a.slug);
    }
    const dupes = [...ids.entries()].filter(([, slugs]) => slugs.length > 1);
    const msg = dupes.map(([id, slugs]) => `${id}: ${slugs.join(" + ")}`).join("; ");
    expect(dupes, `duplicate ADR ids: ${msg}`).toEqual([]);
  });

  intent("INT-ADR-003", "supersede references resolve to existing ADRs", () => {
    const known = new Set(adrs.map((a) => a.slug));
    const broken: string[] = [];
    for (const a of adrs) {
      for (const field of ["supersedes", "superseded_by"]) {
        const ref = a.frontmatter[field];
        if (ref && !known.has(ref)) {
          broken.push(`${a.slug}.${field} -> ${ref}`);
        }
      }
    }
    expect(broken, `unresolved supersede references: ${broken.join(", ")}`).toEqual([]);
  });
});
