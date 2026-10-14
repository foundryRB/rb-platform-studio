import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { expect, test } from 'vitest';
import { readDecisions, renderDecisions } from '../scripts/generate-decisions.mjs';

test('the generated map includes new records and follows changed titles and statuses', () => {
  const directory = mkdtempSync(join(tmpdir(), 'studio-decisions-'));
  try {
    writeFileSync(join(directory, 'ADR-001.md'), '---\ntitle: "ADR-001: Original"\nadr_status: Decided\n---\n');
    let output = renderDecisions(readDecisions(directory));
    expect(output).toContain('| [ADR-001](adr-001/) | Original | Decided |');
    writeFileSync(join(directory, 'ADR-001.md'), '---\ntitle: "ADR-001: Revised"\nadr_status: Superseded\n---\n');
    writeFileSync(join(directory, 'ADR-002.md'), '---\ntitle: "ADR-002: Replacement"\nadr_status: Decided\n---\n');
    output = renderDecisions(readDecisions(directory));
    const [current, superseded] = output.split('## Superseded and deprecated');
    expect(current).toContain('Replacement | Decided');
    expect(current).not.toContain('Revised');
    expect(superseded).toContain('Revised | Superseded');
    expect(output).not.toContain('Original');
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});
