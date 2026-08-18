#!/usr/bin/env node
/**
 * Responsive overflow audit against a live BAKLOG server.
 * Usage:
 *   node scripts/responsive-overflow-audit.mjs [baseUrl]
 *   node scripts/responsive-overflow-audit.mjs --auth-gate [baseUrl]
 *
 * Opt-in (not CI-gated). Needs a local server on 8765.
 *
 * Default matrix (prefer auth disabled so the gate does not block boot):
 *   BAKLOG_PROFILE=perf BAKLOG_AUTH_DISABLED=1 BAKLOG_ADMIN=0
 * Views: dashboard/library/wishlist/connections/pro/itch × 1024/768/390/360/844×390
 * + library Columns/Filters + OUTSIDE overlays at 390 and 844×390.
 *
 * --auth-gate: measure #authGateOverlay only at 390 and 844×390.
 *   Run with AUTH_DISABLED unset so the gate is visible.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';
import { clickViewTab, waitViewSettled } from './audit-view-click.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const argv = process.argv.slice(2).filter((a) => a !== '--');
const AUTH_GATE_ONLY = argv.includes('--auth-gate');
const BASE =
  argv.find((a) => !a.startsWith('--')) || 'http://127.0.0.1:8765';

const VIEWPORTS = [
  { width: 1024, height: 768, label: '1024' },
  { width: 768, height: 1024, label: '768' },
  { width: 390, height: 844, label: '390' },
  { width: 360, height: 740, label: '360' },
  { width: 844, height: 390, label: '844x390' },
];

const OUTSIDE_VIEWPORTS = VIEWPORTS.filter(
  (vp) => vp.label === '390' || vp.label === '844x390',
);

const VIEWS = ['dashboard', 'library', 'wishlist', 'connections', 'pro', 'itch'];

/** Allow 1px subpixel fudge (common on fractional DPR). */
const SCROLL_FUDGE_PX = 1;

async function waitBootCurtainLift(page, { allowAuthGate = false } = {}, timeoutMs = 25000) {
  const authBlocking = await page.evaluate(() => {
    const gate = document.getElementById('authGateOverlay');
    if (!gate || gate.hasAttribute('hidden')) return false;
    return true;
  }).catch(() => false);
  if (authBlocking && !allowAuthGate) {
    throw new Error(
      'auth gate is visible - restart server with BAKLOG_AUTH_DISABLED=1 (and preferably BAKLOG_PROFILE=perf)',
    );
  }
  if (authBlocking && allowAuthGate) return;
  await page.waitForFunction(
    () => !document.documentElement.hasAttribute('data-boot-loading'),
    null,
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

async function measureNamed(page, vp, report, view) {
  await page.waitForTimeout(120);
  const m = await measureOverflow(page);
  pushResult(report, { viewport: vp.label, width: vp.width, view, ...m });
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
    await measureNamed(page, vp, report, 'library-columns');

    await page.evaluate(() => {
      document.getElementById('closeColumnsBtn')?.click();
      document.querySelector('#columnsModal [aria-label="Close"]')?.click();
      const modal = document.getElementById('columnsModal');
      if (modal && !modal.classList.contains('hidden')) modal.classList.add('hidden');
    });
    await page.waitForTimeout(80);

    await page.evaluate(() => {
      document.getElementById('openFiltersBtn')?.click();
    });
    await measureNamed(page, vp, report, 'library-filters');

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

/** OUTSIDE overlays - phone + short landscape only. */
async function smokeOutsideOverlays(page, vp, report) {
  const label = `${vp.label}/outside`;
  try {
    await clickViewTab(page, 'library');
    await waitViewSettled(page, 'library').catch(() => {});

    // Notes sheet
    await page.evaluate(() => {
      const modal = document.getElementById('notesDialogModal');
      if (!modal) return;
      modal.classList.remove('hidden');
      modal.classList.add('flex');
    });
    await measureNamed(page, vp, report, 'notes-modal');
    await page.evaluate(() => {
      const modal = document.getElementById('notesDialogModal');
      modal?.classList.add('hidden');
      modal?.classList.remove('flex');
    });

    // Bug report
    try {
      await page.evaluate(async () => {
        const mod = await import('/js/bug-report.js');
        mod.openBugReportDialog({ note: 'responsive audit' });
      });
      await measureNamed(page, vp, report, 'bug-report');
      await page.evaluate(() => {
        document.querySelector('.baklog-bug-report [data-action="cancel"]')?.click();
        document.querySelector('.baklog-bug-report')?.classList.add('hidden');
      });
    } catch (err) {
      report.failures.push(`${vp.label}/bug-report: ${err.message || err}`);
    }

    // Update modal (synthetic payload)
    try {
      await page.evaluate(async () => {
        const mod = await import('/js/update-check.js');
        mod.showUpdateModal({
          latest: '9.9.9',
          current: '0.0.1',
          notes: 'Responsive audit note line one.\nLine two.',
          url: 'https://example.com',
        });
      });
      await measureNamed(page, vp, report, 'update-modal');
      await page.evaluate(() => {
        document.querySelector('.update-modal-later')?.click();
        document.getElementById('updateReleaseModal')?.classList.add('hidden');
      });
    } catch (err) {
      report.failures.push(`${vp.label}/update-modal: ${err.message || err}`);
    }

    // Kebab menu
    await page.evaluate(() => {
      document.getElementById('kebabBtn')?.click();
      const menu = document.getElementById('kebabMenu');
      menu?.classList.remove('hidden');
    });
    await measureNamed(page, vp, report, 'kebab-menu');
    await page.evaluate(() => {
      document.getElementById('kebabMenu')?.classList.add('hidden');
    });

    // Profile menu
    await page.evaluate(() => {
      document.getElementById('profileMenuTrigger')?.click();
      const menu = document.getElementById('profileMenu');
      menu?.classList.remove('hidden');
    });
    await measureNamed(page, vp, report, 'profile-menu');
    await page.evaluate(() => {
      document.getElementById('profileMenu')?.classList.add('hidden');
    });

    // Claimables module (force visible)
    await page.evaluate(() => {
      const el = document.getElementById('claimableNowModule');
      if (!el) return;
      el.classList.remove('hidden');
      if (!el.innerHTML.trim()) {
        el.innerHTML =
          '<div class="claimable-now p-3"><div class="claim-card">Audit claim card placeholder</div></div>';
      }
    });
    await measureNamed(page, vp, report, 'claimables');
    await page.evaluate(() => {
      document.getElementById('claimableNowModule')?.classList.add('hidden');
    });

    // Header nav sheet
    try {
      await page.evaluate(async () => {
        const mod = await import('/js/header-nav-menu.js');
        mod.openHeaderNavMenu();
      });
      await measureNamed(page, vp, report, 'header-nav-sheet');
      await page.evaluate(async () => {
        const mod = await import('/js/header-nav-menu.js');
        mod.closeHeaderNavMenu?.();
        document.documentElement.classList.remove('header-nav-sheet-open');
        document.getElementById('headerNavPanel')?.setAttribute('hidden', '');
        document.getElementById('headerNavBackdrop')?.setAttribute('hidden', '');
      });
    } catch (err) {
      report.failures.push(`${vp.label}/header-nav-sheet: ${err.message || err}`);
    }

    // Pro compare wrap
    await clickViewTab(page, 'pro');
    await waitViewSettled(page, 'pro').catch(() => {});
    await page.evaluate(() => {
      document.querySelector('.pro-view-compare-wrap')?.scrollIntoView({ block: 'nearest' });
    });
    await measureNamed(page, vp, report, 'pro-compare');
  } catch (err) {
    report.failures.push(`${label}: ${err.message || err}`);
  }
}

async function runAuthGateOnly(browser, report) {
  const context = await browser.newContext();
  const page = await context.newPage();
  for (const vp of OUTSIDE_VIEWPORTS) {
    await page.setViewportSize({ width: vp.width, height: vp.height });
    try {
      await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded', timeout: 25000 });
      await waitBootCurtainLift(page, { allowAuthGate: true });
      const visible = await page.evaluate(() => {
        const gate = document.getElementById('authGateOverlay');
        return !!(gate && !gate.hasAttribute('hidden'));
      });
      if (!visible) {
        report.failures.push(
          `${vp.label}/auth-gate: gate not visible (unset BAKLOG_AUTH_DISABLED for --auth-gate)`,
        );
        continue;
      }
      await measureNamed(page, vp, report, 'auth-gate');
    } catch (err) {
      report.failures.push(`${vp.label}/auth-gate: ${err.message || err}`);
    }
  }
}

async function runMainMatrix(browser, report) {
  const context = await browser.newContext();
  const page = await context.newPage();

  for (const vp of VIEWPORTS) {
    await page.setViewportSize({ width: vp.width, height: vp.height });
    try {
      await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded', timeout: 25000 });
      await waitBootCurtainLift(page);
    } catch (err) {
      report.failures.push(`${vp.label}: boot failed (${err.message || err})`);
      continue;
    }

    for (const view of VIEWS) {
      try {
        const { jumped, hasTab } = await clickViewTab(page, view);
        if (!hasTab) {
          pushResult(report, {
            viewport: vp.label,
            width: vp.width,
            view,
            scrollWidth: 0,
            clientWidth: vp.width,
            overflowPx: 0,
            ok: true,
            skipped: 'tab-absent',
          });
          continue;
        }
        if (jumped) {
          pushResult(report, {
            viewport: vp.label,
            width: vp.width,
            view,
            scrollWidth: 0,
            clientWidth: vp.width,
            overflowPx: 0,
            ok: true,
            skipped: 'itch-tab-jump',
          });
          continue;
        }
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
        report.failures.push(`${vp.label}/${view}: ${err.message || err}`);
      }
    }

    await smokeLibraryOverlays(page, vp, report);

    if (OUTSIDE_VIEWPORTS.some((o) => o.label === vp.label)) {
      await smokeOutsideOverlays(page, vp, report);
    }
  }
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  const report = {
    capturedAt: new Date().toISOString(),
    baseUrl: BASE,
    mode: AUTH_GATE_ONLY ? 'auth-gate' : 'main',
    fudgePx: SCROLL_FUDGE_PX,
    results: [],
    failures: [],
  };

  try {
    if (AUTH_GATE_ONLY) await runAuthGateOnly(browser, report);
    else await runMainMatrix(browser, report);
  } finally {
    await browser.close();
  }

  const outPath = path.join(root, 'scripts', 'responsive-overflow-last-run.json');
  fs.writeFileSync(outPath, `${JSON.stringify(report, null, 2)}\n`, 'utf8');

  const passCount = report.results.filter((r) => r.ok).length;
  console.log(
    `Responsive overflow: ${passCount}/${report.results.length} cells ok ` +
      `(mode=${report.mode})`,
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
