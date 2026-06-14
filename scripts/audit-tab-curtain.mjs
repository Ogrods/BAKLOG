#!/usr/bin/env node
/**
 * Audit tab-switch curtain timing against a live BAKLOG dev server.
 * Fails when the settled view after a switch does not match the target tab.
 *
 * Usage: node scripts/audit-tab-curtain.mjs [baseUrl]
 */
import { chromium } from 'playwright';

const BASE = process.argv[2] || 'http://127.0.0.1:8765';
const TRANSITIONS = [
  ['dashboard', 'library'],
  ['library', 'connections'],
  ['connections', 'library'],
  ['library', 'wishlist'],
  ['wishlist', 'dashboard'],
  ['library', 'pro'],
];

async function clickViewTab(page, view) {
  await page.evaluate((v) => {
    document.querySelector(`.view-tab[data-view="${v}"]`)?.click();
  }, view);
}

function chromeForView(view, snap) {
  if (view === 'dashboard') return snap.dash;
  if (view === 'connections') return snap.conn;
  if (view === 'pro') return snap.pro;
  return snap.table;
}

async function waitSettledView(page, toView, timeoutMs = 10000) {
  return page.evaluate(async ({ toView, timeoutMs }) => {
    const snap = () => ({
      overlay: !!document.getElementById('viewLoadingOverlay')?.classList.contains('show'),
      view: document.documentElement.getAttribute('data-init-view'),
      dash: !document.getElementById('dashboardContainer')?.classList.contains('hidden'),
      conn: !document.getElementById('connectionsContainer')?.classList.contains('hidden'),
      pro: !document.getElementById('proContainer')?.classList.contains('hidden'),
      table: !document.getElementById('tableShell')?.classList.contains('hidden'),
    });
    const sawOverlay = { value: false };
    const start = Date.now();
    let last = snap();
    while (Date.now() - start < timeoutMs) {
      last = snap();
      if (last.overlay) sawOverlay.value = true;
      if (!last.overlay && last.view === toView) {
        return { ok: true, sawOverlay: sawOverlay.value, snap: last };
      }
      await new Promise((r) => setTimeout(r, 40));
    }
    return { ok: false, sawOverlay: sawOverlay.value, snap: last };
  }, { toView, timeoutMs });
}

async function sampleTransition(page, from, to) {
  await clickViewTab(page, from);
  await page.waitForFunction(
    (v) => document.documentElement.getAttribute('data-init-view') === v,
    from,
    { timeout: 10000 },
  );
  await page.waitForTimeout(400);
  await clickViewTab(page, to);
  const result = await waitSettledView(page, to);
  const chromeOk = chromeForView(to, result.snap);
  return {
    ...result,
    chromeOk,
    to,
  };
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  let failed = false;
  try {
    await page.goto(BASE, { waitUntil: 'domcontentloaded', timeout: 15000 });
    await page.waitForFunction(() => document.querySelector('.view-tab[data-view="library"]'), null, { timeout: 15000 });
    await page.waitForTimeout(2000);
    for (const [from, to] of TRANSITIONS) {
      const result = await sampleTransition(page, from, to);
      if (!result.ok || !result.chromeOk) {
        failed = true;
        console.error(`FAIL ${from} -> ${to}`, JSON.stringify(result, null, 2));
      } else {
        console.log(`OK   ${from} -> ${to}${result.sawOverlay ? '' : ' (cached)'}`);
      }
    }
  } finally {
    await browser.close();
  }
  if (failed) process.exit(1);
  console.log('Tab curtain audit passed.');
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
