/**
 * Verify dist/ matches manifest.json and built-frontend invariants.
 * Run after: npm run build
 */
import fs from 'node:fs';
import path from 'node:path';

const root = path.resolve(import.meta.dirname, '..');
const dist = path.join(root, 'dist');
const manifestPath = path.join(dist, 'manifest.json');

if (!fs.existsSync(manifestPath)) {
  console.error('dist/manifest.json missing — run npm run build first');
  process.exit(1);
}

const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
const errors = [];

for (const [key, val] of Object.entries(manifest)) {
  if (key === 'builtAt' || key === 'version') {
    continue;
  }
  if (key === 'js/chunks' && Array.isArray(val)) {
    for (const chunk of val) {
      if (!fs.existsSync(path.join(dist, chunk))) {
        errors.push(`missing chunk: ${chunk}`);
      }
    }
    continue;
  }
  if (typeof val === 'string' && val && !fs.existsSync(path.join(dist, val))) {
    errors.push(`missing manifest entry ${key}: ${val}`);
  }
}

const requiredStatic = [
  'assets/baklog-logo-white.svg',
  'vendor/supabase-js.mjs',
  'js/table-query.worker.js',
];
for (const rel of requiredStatic) {
  if (!fs.existsSync(path.join(dist, rel))) {
    errors.push(`missing dist/${rel}`);
  }
}

const jsDir = path.join(dist, 'js');
if (fs.existsSync(jsDir)) {
  const apps = fs.readdirSync(jsDir).filter((f) => f.startsWith('app-') && f.endsWith('.js'));
  if (apps.length !== 1) {
    errors.push(`expected 1 app-*.js, found ${apps.length}: ${apps.join(', ')}`);
  } else if (manifest['js/app.js'] !== `js/${apps[0]}`) {
    errors.push(`manifest js/app.js mismatch: ${manifest['js/app.js']} vs js/${apps[0]}`);
  }
}

const chunksDir = path.join(dist, 'js/chunks');
if (fs.existsSync(chunksDir)) {
  for (const ent of fs.readdirSync(chunksDir)) {
    if (!ent.endsWith('.js')) {
      continue;
    }
    const text = fs.readFileSync(path.join(chunksDir, ent), 'utf8');
    if (
      text.includes('vendor/supabase')
      && text.includes('"./vendor/supabase')
      && !text.includes('/dist/vendor/supabase')
    ) {
      errors.push(`stale supabase import in ${ent}`);
    }
  }
}

if (errors.length) {
  console.error('dist integrity failed:\n' + errors.map((e) => `  - ${e}`).join('\n'));
  process.exit(1);
}

console.log('dist integrity OK');
