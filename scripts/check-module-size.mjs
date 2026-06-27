/**
 * Fail when any js/*.js module exceeds the committed line budget.
 * Ratchet MAX_LINES down after splitting monolith modules.
 * Run: node scripts/check-module-size.mjs
 */
import fs from 'node:fs';
import path from 'node:path';

const root = path.resolve(import.meta.dirname, '..');
const jsDir = path.join(root, 'js');
const MAX_LINES = 3800;
const EXEMPT = new Set(['table-query.worker.js']);

/** Monolith runner — split incrementally; budget ratchets down after extractions. */
const RUNNER_MAX_LINES = 2200;
const RUNNER_FILES = ['js/fetcher/runner/index.js'];

function lineCount(filePath) {
  return fs.readFileSync(filePath, 'utf8').split(/\r?\n/).length;
}

const offenders = [];
for (const ent of fs.readdirSync(jsDir, { withFileTypes: true })) {
  if (!ent.isFile() || !ent.name.endsWith('.js')) continue;
  if (EXEMPT.has(ent.name)) continue;
  const p = path.join(jsDir, ent.name);
  const lines = lineCount(p);
  if (lines > MAX_LINES) offenders.push({ file: `js/${ent.name}`, lines, max: MAX_LINES });
}

for (const rel of RUNNER_FILES) {
  const p = path.join(root, rel);
  if (!fs.existsSync(p)) continue;
  const lines = lineCount(p);
  if (lines > RUNNER_MAX_LINES) {
    offenders.push({ file: rel, lines, max: RUNNER_MAX_LINES });
  }
}

if (offenders.length) {
  console.error('Module size budget exceeded:');
  for (const o of offenders.sort((a, b) => b.lines - a.lines)) {
    console.error(`  ${o.file}: ${o.lines} lines (max ${o.max})`);
  }
  process.exit(1);
}

console.log(`OK — js/*.js ≤ ${MAX_LINES} lines; runner ≤ ${RUNNER_MAX_LINES}.`);
