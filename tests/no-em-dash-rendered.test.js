// @vitest-environment node
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const EM = '\u2014';

const RENDERED_LINES = [
  ['js/filters-ui.js', 'click again to clear'],
  ['js/dashboard-charts.js', 'no rated games'],
];

/** Batch K surface: user-facing HTML + known copy modules (comments exempt). */
const SCAN_FILES = [
  'index.html',
  'js/sponsored-deals.js',
  'js/metric-tips.js',
  ...fs
    .readdirSync(path.join(root, 'web'), { withFileTypes: true })
    .filter((d) => d.isFile() && d.name.endsWith('.html'))
    .map((d) => path.join('web', d.name).replace(/\\/g, '/')),
];

/** Strip line/block/HTML comments before scanning (AGENTS exempts comments). */
function stripComments(source) {
  let out = '';
  let i = 0;
  const n = source.length;
  while (i < n) {
    const c = source[i];
    const next = source[i + 1];
    if (c === '/' && next === '/') {
      i += 2;
      while (i < n && source[i] !== '\n') i += 1;
      continue;
    }
    if (c === '/' && next === '*') {
      i += 2;
      while (i < n - 1 && !(source[i] === '*' && source[i + 1] === '/')) i += 1;
      i = Math.min(i + 2, n);
      continue;
    }
    if (c === '<' && source.startsWith('<!--', i)) {
      i += 4;
      while (i < n - 2 && !source.startsWith('-->', i)) i += 1;
      i = Math.min(i + 3, n);
      continue;
    }
    out += c;
    i += 1;
  }
  return out;
}

describe('rendered copy has no em dashes', () => {
  it.each(RENDERED_LINES)('%s lines containing "%s"', (file, marker) => {
    const lines = fs
      .readFileSync(path.join(root, file), 'utf8')
      .split(/\r?\n/)
      .filter((line) => line.includes(marker));
    expect(lines.length).toBeGreaterThan(0);
    for (const line of lines) expect(line).not.toContain(EM);
  });

  it.each(SCAN_FILES)('%s has no em dash outside comments', (rel) => {
    const raw = fs.readFileSync(path.join(root, rel), 'utf8');
    expect(stripComments(raw)).not.toContain(EM);
  });
});
