#!/usr/bin/env node
/**
 * Audit header bottom rule visibility across table vs non-table views.
 * Usage: node scripts/audit-header-rule.mjs [baseUrl]
 */
import { chromium } from 'playwright';

const BASE = process.argv[2] || 'http://127.0.0.1:8765';
const VIEWS = ['dashboard', 'library', 'wishlist', 'itch', 'connections', 'pro'];

async function clickView(page, view) {
  await page.evaluate((v) => {
    document.querySelector(`.view-tab[data-view="${v}"]`)?.click();
  }, view);
  await page.waitForFunction(
    (v) => document.documentElement.getAttribute('data-init-view') === v,
    view,
    { timeout: 20000 },
  );
  await page.waitForFunction(
    () => {
      const v = document.documentElement.getAttribute('data-init-view');
      if (v === 'dashboard' || v === 'connections' || v === 'pro') return true;
      return !!window.__baklogBootPerf?.dashboardDataReady
        || document.getElementById('summary')?.children?.length > 0;
    },
    null,
    { timeout: 20000 },
  );
  await page.waitForTimeout(600);
}

async function sampleView(page, view) {
  await clickView(page, view);
  return page.evaluate(() => {
    const header = document.querySelector('header.app-header');
    const row = document.querySelector('.app-header-row');
    const summary = document.getElementById('summary');
    const cs = header ? getComputedStyle(header) : null;
    const rowCs = row ? getComputedStyle(row) : null;
    const hRect = header?.getBoundingClientRect();
    const rowRect = row?.getBoundingClientRect();
    const hasRuleShadow = cs?.boxShadow && cs.boxShadow !== 'none';
    const rowHasRuleShadow = rowCs?.boxShadow && rowCs.boxShadow !== 'none';
    return {
      view: document.documentElement.getAttribute('data-init-view'),
      hasRuleShadow,
      rowHasRuleShadow,
      boxShadow: cs?.boxShadow ?? null,
      rowBoxShadow: rowCs?.boxShadow ?? null,
      headerPosition: cs?.position ?? null,
      summaryHidden: summary?.classList.contains('hidden') ?? null,
      summaryChildCount: summary?.children?.length ?? 0,
      gapRowToHeaderBottom: hRect && rowRect ? +(hRect.bottom - rowRect.bottom).toFixed(1) : null,
    };
  });
}

function ruleOk(snap) {
  if (!snap.rowHasRuleShadow) return false;
  // Library/wishlist/itch keep summary chips below the header row — gap to
  // header bottom includes that strip; row shadow is the signal we care about.
  if (snap.summaryHidden === false && (snap.summaryChildCount ?? 0) > 0) return true;
  return snap.gapRowToHeaderBottom < 16;
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  let failed = false;
  try {
    await page.goto(BASE, { waitUntil: 'domcontentloaded', timeout: 15000 });
    await page.waitForSelector('.view-tab[data-view="library"]', { timeout: 15000 });
    await page.waitForTimeout(2000);
    for (const view of VIEWS) {
      const tab = page.locator(`.view-tab[data-view="${view}"]`);
      if ((await tab.count()) === 0) {
        console.log(`SKIP ${view} (tab absent)`);
        continue;
      }
      const snap = await sampleView(page, view);
      const ok = ruleOk(snap);
      if (!ok) {
        failed = true;
        console.error(`FAIL ${view}`, JSON.stringify(snap, null, 2));
      } else {
        console.log(`OK   ${view}`, JSON.stringify(snap));
      }
    }
  } finally {
    await browser.close();
  }
  if (failed) process.exit(1);
  console.log('Header rule audit passed.');
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
