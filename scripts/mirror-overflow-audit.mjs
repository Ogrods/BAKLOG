#!/usr/bin/env node
/**
 * Hosted /mirror overflow + virtual-scroll audit.
 * Usage:
 *   node scripts/mirror-overflow-audit.mjs [baseUrl]
 *
 * Serves landing/ on an ephemeral port when baseUrl is omitted.
 * Injects 2000 synthetic rows via window.__baklogMirrorTest (no auth).
 *
 * Matrix: 1024×800, 768×900, 390×844, 360×740, 844×390
 */
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const landingRoot = path.join(root, 'landing');
const OUT = path.join(root, 'scripts', 'mirror-overflow-last-run.json');

const VIEWPORTS = [
  { width: 1024, height: 800, label: '1024' },
  { width: 768, height: 900, label: '768' },
  { width: 390, height: 844, label: '390' },
  { width: 360, height: 740, label: '360' },
  { width: 844, height: 390, label: '844x390' },
];

const SYNTHETIC_N = 2000;
const MAX_PAINTED = 80;

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.json': 'application/json',
};

function startStaticServer() {
  const server = http.createServer((req, res) => {
    try {
      const url = new URL(req.url || '/', 'http://127.0.0.1');
      let rel = decodeURIComponent(url.pathname);
      if (rel === '/' || rel === '/mirror') rel = '/mirror.html';
      if (rel.includes('..')) {
        res.writeHead(400);
        res.end('bad path');
        return;
      }
      const filePath = path.join(landingRoot, rel.replace(/^\//, ''));
      if (!filePath.startsWith(landingRoot) || !fs.existsSync(filePath) || fs.statSync(filePath).isDirectory()) {
        res.writeHead(404);
        res.end('not found');
        return;
      }
      const ext = path.extname(filePath);
      res.writeHead(200, { 'Content-Type': MIME[ext] || 'application/octet-stream' });
      fs.createReadStream(filePath).pipe(res);
    } catch (err) {
      res.writeHead(500);
      res.end(String(err));
    }
  });
  return new Promise((resolve) => {
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address();
      resolve({ server, baseUrl: `http://127.0.0.1:${port}` });
    });
  });
}

function makeSyntheticRows(n) {
  const stores = ['Steam', 'Epic', 'GOG', 'Xbox', 'PlayStation'];
  const statuses = ['backlog', 'playing', 'finished', 'next'];
  const rows = [];
  for (let i = 0; i < n; i += 1) {
    rows.push({
      title: `Synthetic Game ${String(i + 1).padStart(4, '0')}`,
      store: stores[i % stores.length].toLowerCase(),
      storeLabel: stores[i % stores.length],
      status: statuses[i % statuses.length],
      statusLabel: statuses[i % statuses.length],
      playtimeHours: (i % 40) + 0.5,
      hltbMain: (i % 20) + 1,
      hltbExtra: (i % 10) + 2,
      notes: i % 17 === 0 ? 'note' : '',
      coverUrl: i % 5 === 0 ? 'https://cdn.akamai.steamstatic.com/steam/apps/570/header.jpg' : '',
      steamPercent: 70 + (i % 30),
      metacritic: 60 + (i % 40),
      priceLabel: i % 9 === 0 ? '$4.99 (-50%)' : '',
      released: '2020-01-01',
      lastPlayed: i % 3 === 0 ? 'Jan 2, 2026' : '',
      genres: i % 4 === 0 ? ['Action', 'RPG'] : [],
      platforms: '',
    });
  }
  return rows;
}

async function measureViewport(page, vp) {
  await page.setViewportSize({ width: vp.width, height: vp.height });
  await page.waitForTimeout(120);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(80);
  await page.evaluate(() => {
    window.__baklogMirrorTest?.render?.();
  });
  await page.waitForTimeout(100);

  const top = await page.evaluate(() => {
    const de = document.documentElement;
    const body = document.body;
    const painted = document.querySelectorAll('#mirrorTableBody tr[data-row-index]').length;
    const spacers = document.querySelectorAll('#mirrorTableBody tr.mirror-virtual-spacer').length;
    return {
      overflowX: de.scrollWidth > de.clientWidth + 1 || body.scrollWidth > body.clientWidth + 1,
      scrollWidth: de.scrollWidth,
      clientWidth: de.clientWidth,
      painted,
      spacers,
      filtered: window.__baklogMirrorTest?.getFilteredCount?.() ?? -1,
      usesVirtual: window.__baklogMirrorTest?.usesVirtual?.() ?? false,
    };
  });

  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight * 0.45));
  await page.waitForTimeout(120);
  const mid = await page.evaluate(() => ({
    painted: document.querySelectorAll('#mirrorTableBody tr[data-row-index]').length,
  }));

  return { ...top, paintedMid: mid.painted };
}

async function main() {
  const argUrl = process.argv.slice(2).find((a) => !a.startsWith('--'));
  let server = null;
  let baseUrl = argUrl;
  if (!baseUrl) {
    ({ server, baseUrl } = await startStaticServer());
  }

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  const results = [];
  let failed = false;

  try {
    await page.goto(`${baseUrl.replace(/\/$/, '')}/mirror.html`, { waitUntil: 'domcontentloaded', timeout: 30_000 });
    await page.waitForFunction(() => typeof window.__baklogMirrorTest?.setRows === 'function', null, {
      timeout: 15_000,
    });
    const rows = makeSyntheticRows(SYNTHETIC_N);
    await page.evaluate((payload) => {
      window.__baklogMirrorTest.setRows(payload);
    }, rows);

    for (const vp of VIEWPORTS) {
      const m = await measureViewport(page, vp);
      const okOverflow = !m.overflowX;
      const okVirtual = m.usesVirtual === true;
      const okPainted = m.painted <= MAX_PAINTED && m.paintedMid <= MAX_PAINTED;
      const okSpacers = m.spacers >= 1;
      const ok = okOverflow && okVirtual && okPainted && okSpacers;
      if (!ok) failed = true;
      results.push({
        viewport: vp.label,
        ok,
        okOverflow,
        okVirtual,
        okPainted,
        okSpacers,
        ...m,
      });
      const mark = ok ? 'PASS' : 'FAIL';
      console.log(
        `${mark} ${vp.label}: overflowX=${m.overflowX} virtual=${m.usesVirtual} painted=${m.painted}/${m.paintedMid} spacers=${m.spacers}`,
      );
    }

    // Small filter → oneshot paint (no virtual)
    await page.setViewportSize({ width: 1024, height: 800 });
    await page.fill('#mirrorSearch', 'Synthetic Game 0001');
    await page.waitForTimeout(150);
    const small = await page.evaluate(() => ({
      filtered: window.__baklogMirrorTest.getFilteredCount(),
      painted: window.__baklogMirrorTest.getPaintedRowCount(),
      usesVirtual: window.__baklogMirrorTest.usesVirtual(),
    }));
    const smallOk = small.filtered <= 5 && small.usesVirtual === false && small.painted === small.filtered;
    if (!smallOk) failed = true;
    results.push({ viewport: 'filter-small', ok: smallOk, ...small });
    console.log(
      `${smallOk ? 'PASS' : 'FAIL'} filter-small: filtered=${small.filtered} painted=${small.painted} virtual=${small.usesVirtual}`,
    );
  } finally {
    await browser.close();
    if (server) server.close();
  }

  fs.writeFileSync(OUT, JSON.stringify({ baseUrl, results, failed }, null, 2));
  console.log(`Wrote ${OUT}`);
  if (failed) {
    process.exitCode = 1;
  }
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
