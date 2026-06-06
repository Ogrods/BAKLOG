/**
 * Phase 0 baseline: on-disk asset sizes for the raw (unbuilt) frontend.
 * Run: node scripts/measure-baseline.mjs
 * Output: scripts/frontend-baseline.json
 */
import fs from 'node:fs';
import path from 'node:path';

const root = path.resolve(import.meta.dirname, '..');

function sizeKb(filePath) {
  try {
    return Math.round((fs.statSync(filePath).size / 1024) * 10) / 10;
  } catch {
    return null;
  }
}

function dirSizeKb(dirPath) {
  if (!fs.existsSync(dirPath)) return 0;
  let total = 0;
  for (const ent of fs.readdirSync(dirPath, { withFileTypes: true })) {
    const p = path.join(dirPath, ent.name);
    if (ent.isDirectory()) total += dirSizeKb(p) * 1024;
    else total += fs.statSync(p).size;
  }
  return Math.round((total / 1024) * 10) / 10;
}

function countJsModules(dir) {
  let n = 0;
  for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, ent.name);
    if (ent.isDirectory()) n += countJsModules(p);
    else if (ent.name.endsWith('.js') || ent.name.endsWith('.mjs')) n += 1;
  }
  return n;
}

const jsDir = path.join(root, 'js');
const baseline = {
  capturedAt: new Date().toISOString(),
  note: 'Raw dev frontend (no bundle). Chart.js and Supabase are lazy-loaded off critical path.',
  assets: {
    'app.css': sizeKb(path.join(root, 'app.css')),
    'tailwind.css': sizeKb(path.join(root, 'tailwind.css')),
    'index.html': sizeKb(path.join(root, 'index.html')),
    'vendor/chart.umd.min.js': sizeKb(path.join(root, 'vendor/chart.umd.min.js')),
    'js/ (all modules)': dirSizeKb(jsDir),
    'js/module_count': countJsModules(jsDir),
    'js/vendor/supabase-js.mjs': sizeKb(path.join(root, 'js/vendor/supabase-js.mjs')),
  },
  lazyOffCriticalPath: [
    'vendor/chart.umd.min.js via js/chart-loader.js (dashboard only)',
    'js/vendor/supabase-js.mjs via js/auth-gate.js (account auth only)',
  ],
  devCachePolicy: 'Cache-Control: no-store on .js/.mjs/.css/.html (server.py Handler)',
};

const out = path.join(root, 'scripts/frontend-baseline.json');
fs.writeFileSync(out, JSON.stringify(baseline, null, 2));
console.log(JSON.stringify(baseline, null, 2));
console.log(`\nWrote ${out}`);
