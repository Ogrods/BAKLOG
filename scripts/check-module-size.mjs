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

function lineCount(filePath) {
  return fs.readFileSync(filePath, 'utf8').split(/\r?\n/).length;
}

const offenders = [];
for (const ent of fs.readdirSync(jsDir, { withFileTypes: true })) {
  if (!ent.isFile() || !ent.name.endsWith('.js')) continue;
  if (EXEMPT.has(ent.name)) continue;
  const p = path.join(jsDir, ent.name);
  const lines = lineCount(p);
  if (lines > MAX_LINES) offenders.push({ file: `js/${ent.name}`, lines });
}

if (offenders.length) {
  console.error(`Module size budget exceeded (max ${MAX_LINES} lines):`);
  for (const o of offenders.sort((a, b) => b.lines - a.lines)) {
    console.error(`  ${o.file}: ${o.lines} lines`);
  }
  process.exit(1);
}

console.log(`OK — all js/*.js modules are within ${MAX_LINES} lines.`);
