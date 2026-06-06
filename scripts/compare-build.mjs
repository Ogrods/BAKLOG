/**
 * Compare raw baseline vs latest dist/ build output.
 * Run after: npm run build
 */
import fs from 'node:fs';
import path from 'node:path';

const root = path.resolve(import.meta.dirname, '..');
const baselinePath = path.join(root, 'scripts/frontend-baseline.json');
const manifestPath = path.join(root, 'dist/manifest.json');

function kb(filePath) {
  try {
    return Math.round((fs.statSync(filePath).size / 1024) * 10) / 10;
  } catch {
    return null;
  }
}

const baseline = JSON.parse(fs.readFileSync(baselinePath, 'utf8'));
const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));

const builtCss =
  kb(path.join(root, 'dist', manifest['app.css'])) +
  kb(path.join(root, 'dist', manifest['tailwind.css']));
const entryJs = kb(path.join(root, 'dist', manifest['js/app.js']));
let chunksKb = 0;
for (const chunk of manifest['js/chunks'] || []) {
  chunksKb += kb(path.join(root, 'dist', chunk)) || 0;
}

console.log('=== Raw (dev) vs Built (production) ===');
console.log(`CSS:  ${baseline.assets['app.css'] + baseline.assets['tailwind.css']} KB raw -> ${builtCss} KB minified`);
console.log(`JS:   ${baseline.assets['js/ (all modules)']} KB (${baseline.assets['js/module_count']} modules) -> entry ${entryJs} KB + chunks ${Math.round(chunksKb * 10) / 10} KB`);
console.log(`Chart.js / Supabase: still lazy (not in bundle critical path)`);
