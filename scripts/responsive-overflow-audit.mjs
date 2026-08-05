#!/usr/bin/env node
/**
 * Responsive overflow audit against a live BAKLOG server.
 * Usage: node scripts/responsive-overflow-audit.mjs [baseUrl]
 *
 * Opt-in (not CI-gated). Needs a local server on 8765. Prefer the same gate as
 * perf audit so the auth overlay does not block boot:
 *   BAKLOG_PROFILE=perf BAKLOG_AUTH_DISABLED=1 BAKLOG_ADMIN=0
 * (see scripts/start-perf-server.ps1).
 *
 * Matrix: tracker RESPONSIVE_TEST_MATRIX (1024 / 768 / 390 / 360) plus a phone
 * landscape cell (844×390). Settled views + one library overlay smoke
 * (Columns modal + Filters drawer open/close).
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const BASE = process.argv[2] || 'http://127.0.0.1:8765';

const VIEWPORTS = [
  { width: 1024, height: 768, label: '1024' },
  { width: 768, height: 1024, label: '768' },
  { width: 390, height: 844, label: '390' },
  { width: 360, height: 740, label: '360' },
  { width: 844, height: 390, label: '844x390' },
];

const VIEWS = ['dashboard', 'library', 'wishlist', 'connections', 'pro'];

/** Allow 1px subpixel fudge (common on fractional DPR). */
const SCROLL_FUDGE_PX = 1;

async function clickViewTab(page, view) {
  await page.evaluate((v) => {
    const tab = document.querySelector(`.view-tab[data-view="${v}"]`);
    if (tab) {
      tab.click();
      return;
    }
    document.querySelector(`#headerNavSheet .view-tab[data-view="${v}"]`)?.click();
  }, view);
}

async function waitBootCurtainLift(page, timeoutMs = 25000) {
  const authBlocking = await page.evaluate(() => {
    const gate = document.getElementById('authGateOverlay');
    if (!gate || gate.hasAttribute('hidden')) return false;
    return true;
  }).catch(() => false);
  if (authBlocking) {
    throw new Error(
      'auth gate is visible - restart server with BAKLOG_AUTH_DISABLED=1 (and preferably BAKLOG_PROFILE=perf)',
    );
  }
  await page.waitForFunction(
    () => !document.documentElement.hasAttribute('data-boot-loading'),
    null,
    { timeout: timeoutMs },
  );
}

async function waitViewSettled(page, view, timeoutMs = 12000) {
  await page.waitForFunction(
    (v) => {
      const overlay = !!document
        .getElementById('viewLoadingOverlay')
        ?.classList.contains('show');
      const active = document.documentElement.getAttribute('data-init-view');
      return !overlay && active === v;
    },
    view,
    { timeout: timeoutMs },
  );
}

async function measureOverflow(page) {
  return page.evaluate((fudge) => {
    const rootEl = document.documentElement;
    const body = document.body;
    const scrollW = Math.max(rootEl.scrollWidth, body?.scrollWidth || 0);
    const clientW = rootEl.clientWidth || window.innerWidth;
    const overflowPx = Math.max(0, scrollW - clientW);
    return {
      scrollWidth: scrollW,
      clientWidth: clientW,
      overflowPx,
      ok: overflowPx <= fudge,
    };
  }, SCROLL_FUDGE_PX);
}

function pushResult(report, row) {
  report.results.push(row);
  if (!row.ok) {
    report.failures.push(
      `${row.viewport}/${row.view}: overflow ${row.overflowPx}px (scrollWidth=${row.scrollWidth}, clientWidth=${row.clientWidth})`,
    );
  }
}

/** Open Columns + Filters on library, measure, then close. */
async function smokeLibraryOverlays(page, vp, report) {
  const label = `${vp.label}/library-overlays`;
  try {
    await clickViewTab(page, 'library');
    await waitViewSettled(page, 'library');

    await page.evaluate(() => {
      document.getElementById('openColumnsBtn')?.click();
    });
    await page.waitForTimeout(150);
    let m = await measureOverflow(page);
    pushResult(report, { viewport: vp.label, width: vp.width, view: 'library-columns', ...m });

    await page.evaluate(() => {
      document.getElementById('closeColumnsBtn')?.click();
      document.querySelector('#columnsModal [aria-label="Close"]')?.click();
      const modal = document.getElementById('columnsModal');
      if (modal && !modal.classList.contains('hidden')) modal.classList.add('hidden');
    });
    await page.waitForTimeout(100);

    await page.evaluate(() => {
      document.getElementById('openFiltersBtn')?.click();
    });
    await page.waitForTimeout(150);
    m = await measureOverflow(page);
    pushResult(report, { viewport: vp.label, width: vp.width, view: 'library-filters', ...m });

    await page.evaluate(() => {
      document.getElementById('closeFiltersBtn')?.click();
      const drawer = document.getElementById('filterDrawer');
      drawer?.classList.remove('open');
      document.getElementById('filterDrawerBackdrop')?.classList.remove('open');
    });
  } catch (err) {
    report.failures.push(`${label}: ${err.message || err}`);
  }
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  const report = {
    capturedAt: new Date().toISOString(),
    baseUrl: BASE,
    fudgePx: SCROLL_FUDGE_PX,
    results: [],
    failures: [],
  };

  try {
    const context = await browser.newContext();
    const page = await context.newPage();

    for (const vp of VIEWPORTS) {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      try {
        await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded', timeout: 25000 });
        await waitBootCurtainLift(page);
      } catch (err) {
        report.failures.push(
          `${vp.label}: boot failed (${err.message || err})`,
        );
        continue;
      }

      for (const view of VIEWS) {
        try {
          await clickViewTab(page, view);
          await waitViewSettled(page, view);
          await page.waitForTimeout(200);
          const m = await measureOverflow(page);
          pushResult(report, {
            viewport: vp.label,
            width: vp.width,
            view,
            ...m,
          });
        } catch (err) {
          report.failures.push(
            `${vp.label}/${view}: ${err.message || err}`,
          );
        }
      }

      await smokeLibraryOverlays(page, vp, report);
    }
  } finally {
    await browser.close();
  }

  const outPath = path.join(root, 'scripts', 'responsive-overflow-last-run.json');
  fs.writeFileSync(outPath, `${JSON.stringify(report, null, 2)}\n`, 'utf8');

  const passCount = report.results.filter((r) => r.ok).length;
  console.log(
    `Responsive overflow: ${passCount}/${report.results.length} cells ok ` +
      `(${VIEWPORTS.length} viewports × ${VIEWS.length} views + overlays)`,
  );
  if (report.failures.length) {
    console.error('Failures:');
    for (const f of report.failures) console.error(`  - ${f}`);
    console.error(`Report: ${path.relative(root, outPath)}`);
    process.exit(1);
  }
  console.log(`Passed. Report: ${path.relative(root, outPath)}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
