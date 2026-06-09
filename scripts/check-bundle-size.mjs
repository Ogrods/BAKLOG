/**
 * Enforce committed production bundle ceilings (size-budget.json).
 * Gates critical-path entry JS + CSS only (lazy chunks are not summed).
 * Requires: npm run build (dist/manifest.json must exist).
 * Run: node scripts/check-bundle-size.mjs
 *      node scripts/check-bundle-size.mjs --write
 */
import fs from 'node:fs';
import path from 'node:path';

const root = path.resolve(import.meta.dirname, '..');
const budgetPath = path.join(root, 'size-budget.json');
const manifestPath = path.join(root, 'dist/manifest.json');
const writeMode = process.argv.includes('--write');

function kb(filePath) {
  try {
    return Math.round((fs.statSync(filePath).size / 1024) * 10) / 10;
  } catch {
    return null;
  }
}

if (!fs.existsSync(manifestPath)) {
  console.error('dist/manifest.json missing — run npm run build first');
  process.exit(1);
}

const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
const entryJs = kb(path.join(root, 'dist', manifest['js/app.js']));
const cssKb = Math.round(
  ((kb(path.join(root, 'dist', manifest['app.css'])) || 0) +
    (kb(path.join(root, 'dist', manifest['tailwind.css'])) || 0)) * 10,
) / 10;

const measured = { entryJsKb: entryJs, cssKb };

if (writeMode) {
  const budget = {
    note: 'Critical-path dist/ ceilings (entry js/app.js + CSS). Lazy chunks excluded. Refresh: npm run build && node scripts/check-bundle-size.mjs --write',
    capturedAt: new Date().toISOString().slice(0, 10),
    maxEntryJsKb: Math.ceil(entryJs * 1.08),
    maxCssKb: Math.ceil(cssKb * 1.05),
  };
  fs.writeFileSync(budgetPath, `${JSON.stringify(budget, null, 2)}\n`);
  console.log(`Wrote ${budgetPath}`);
  console.log(JSON.stringify(budget, null, 2));
  process.exit(0);
}

const budget = JSON.parse(fs.readFileSync(budgetPath, 'utf8'));
const failures = [];
if (entryJs > budget.maxEntryJsKb) {
  failures.push(`entry js/app.js: ${entryJs} KB > ${budget.maxEntryJsKb} KB`);
}
if (cssKb > budget.maxCssKb) {
  failures.push(`css total: ${cssKb} KB > ${budget.maxCssKb} KB`);
}

if (failures.length) {
  console.error('Bundle size budget exceeded:');
  for (const f of failures) console.error(`  ${f}`);
  process.exit(1);
}

console.log('OK — bundle within budget:', measured);
