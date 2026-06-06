/**
 * Production frontend build: minified CSS + bundled ESM JS with content hashes.
 * Output: dist/ + dist/manifest.json
 * Dev/test continue to use raw js/*.js and source CSS (zero-build path).
 */
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import * as esbuild from 'esbuild';

const root = path.resolve(import.meta.dirname, '..');
const distDir = path.join(root, 'dist');
const manifestPath = path.join(distDir, 'manifest.json');

function sha256Short(bytes) {
  return crypto.createHash('sha256').update(bytes).digest('hex').slice(0, 8);
}

function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true });
}

function writeHashedFile(srcBytes, logicalName, ext) {
  const hash = sha256Short(srcBytes);
  const base = logicalName.replace(/\.[^.]+$/, '');
  const outName = `${base}.${hash}${ext}`;
  const outPath = path.join(distDir, outName);
  fs.writeFileSync(outPath, srcBytes);
  return outName;
}

function copyDir(src, dest) {
  ensureDir(dest);
  for (const ent of fs.readdirSync(src, { withFileTypes: true })) {
    const s = path.join(src, ent.name);
    const d = path.join(dest, ent.name);
    if (ent.isDirectory()) copyDir(s, d);
    else fs.copyFileSync(s, d);
  }
}

async function buildCss() {
  const manifest = {};
  for (const logical of ['tailwind.css', 'app.css']) {
    const entry = path.join(root, logical);
    const tmpOut = path.join(distDir, `.tmp-${logical}`);
    await esbuild.build({
      entryPoints: [entry],
      outfile: tmpOut,
      minify: true,
      logLevel: 'silent',
    });
    const bytes = fs.readFileSync(tmpOut);
    fs.unlinkSync(tmpOut);
    const hashed = writeHashedFile(bytes, logical, '.css');
    manifest[logical] = hashed;
    console.log(`  ${logical}: ${(bytes.length / 1024).toFixed(1)} KB -> dist/${hashed}`);
  }
  return manifest;
}

async function buildJs() {
  const jsOutDir = path.join(distDir, 'js');
  ensureDir(jsOutDir);
  const result = await esbuild.build({
    entryPoints: [path.join(root, 'js/app.js')],
    bundle: true,
    splitting: true,
    format: 'esm',
    platform: 'browser',
    target: ['es2020'],
    minify: true,
    sourcemap: false,
    outdir: distDir,
    entryNames: 'js/[name]-[hash]',
    chunkNames: 'js/chunks/[name]-[hash]',
    assetNames: 'assets/[name]-[hash]',
    logLevel: 'info',
    // Keep lazy vendor imports as runtime fetches (copied to dist/vendor below).
    plugins: [{
      name: 'external-js-vendor',
      setup(build) {
        // Bundled entry lives at dist/js/app-[hash].js; vendor sits at dist/vendor/.
        build.onResolve({ filter: /vendor\/supabase-js\.mjs$/ }, () => ({
          path: '../vendor/supabase-js.mjs',
          external: true,
        }));
      },
    }],
  });

  const manifest = {};
  for (const out of result.outputFiles || []) {
    const rel = path.relative(distDir, out.path).replace(/\\/g, '/');
    if (rel.startsWith('js/app-') && rel.endsWith('.js')) {
      manifest['js/app.js'] = rel;
      console.log(`  js/app.js -> dist/${rel}`);
    }
  }

  // esbuild metafile when write:true doesn't populate outputFiles; scan disk.
  if (!manifest['js/app.js']) {
    for (const ent of fs.readdirSync(jsOutDir)) {
      if (ent.startsWith('app-') && ent.endsWith('.js')) {
        manifest['js/app.js'] = `js/${ent}`;
        console.log(`  js/app.js -> dist/${manifest['js/app.js']}`);
        break;
      }
    }
  }

  // Record chunk files for immutable-cache detection (optional).
  const chunks = [];
  const chunksDir = path.join(distDir, 'js/chunks');
  if (fs.existsSync(chunksDir)) {
    for (const ent of fs.readdirSync(chunksDir)) {
      if (ent.endsWith('.js')) chunks.push(`js/chunks/${ent}`);
    }
  }
  manifest['js/chunks'] = chunks;

  const workerDir = path.join(distDir, 'js');
  for (const ent of fs.readdirSync(workerDir)) {
    if (ent.includes('table-query.worker') && ent.endsWith('.js')) {
      manifest['js/table-query.worker.js'] = `js/${ent}`;
    }
  }

  return manifest;
}

async function main() {
  const args = new Set(process.argv.slice(2));
  const cssOnly = args.has('--css-only');
  const jsOnly = args.has('--js-only');
  ensureDir(distDir);

  let prior = {};
  if (fs.existsSync(manifestPath)) {
    try {
      prior = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
    } catch {
      prior = {};
    }
  }

  const manifest = {
    builtAt: new Date().toISOString(),
    version: JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8')).version,
    ...prior,
  };

  if (!jsOnly) {
    console.log('Minifying CSS -> dist/');
    Object.assign(manifest, await buildCss());
  }
  if (!cssOnly) {
    console.log('Bundling JS -> dist/');
    Object.assign(manifest, await buildJs());
    const vendorSrc = path.join(root, 'js/vendor');
    if (fs.existsSync(vendorSrc)) {
      copyDir(vendorSrc, path.join(distDir, 'vendor'));
      console.log('  copied js/vendor -> dist/vendor');
    }
  }

  fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2));
  console.log(`Wrote ${manifestPath}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
