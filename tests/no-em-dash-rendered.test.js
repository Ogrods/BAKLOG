// @vitest-environment node
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

const RENDERED_LINES = [
  ['js/filters-ui.js', 'click again to clear'],
  ['js/dashboard-charts.js', 'no rated games'],
];

describe('rendered copy has no em dashes', () => {
  it.each(RENDERED_LINES)('%s lines containing "%s"', (file, marker) => {
    const lines = fs
      .readFileSync(path.join(root, file), 'utf8')
      .split(/\r?\n/)
      .filter(line => line.includes(marker));
    expect(lines.length).toBeGreaterThan(0);
    for (const line of lines) expect(line).not.toContain('\u2014');
  });
});
