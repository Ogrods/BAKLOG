#!/usr/bin/env node
/**
 * Modal geometry audit — Playwright matrix for app-modal body/actions layout.
 * Usage: node scripts/modal-geometry-audit.mjs [baseUrl]
 * Requires: live server with BAKLOG_PROFILE=perf (see start-modal-geometry.ps1).
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium, devices } from 'playwright';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const BASE = process.argv[2] || 'http://127.0.0.1:8765';
const OUT = path.join(root, 'scripts', 'modal-geometry-last-run.json');

const VIEWPORTS = [
  {
    name: 'shortLand',
    width: 800,
    height: 480,
    isMobile: true,
    hasTouch: true,
  },
  { name: 'phone390', width: 390, height: 844 },
  { name: 'mid640', width: 640, height: 800 },
  { name: 'desk1280', width: 1280, height: 800 },
];

const MODALS = [
  { id: 'hltb', modalId: 'hltbEstimateModal', open: 'openHltb', close: 'closeHltb' },
  { id: 'notes', modalId: 'notesDialogModal', open: 'openNotes', close: 'closeNotes' },
  { id: 'addGame', modalId: 'addGameModal', open: 'openAddGame', close: 'closeAddGame' },
];

async function waitBoot(page, timeoutMs = 60000) {
  await page.waitForFunction(
    () => !document.documentElement.hasAttribute('data-boot-loading'),
    null,
    { timeout: timeoutMs },
  );
  await page.waitForFunction(
    () => !!window.__baklogModalGeom?.measure,
    null,
    { timeout: timeoutMs },
  );
}

async function clickViewTab(page, view) {
  await page.evaluate((v) => {
    document.querySelector(`.view-tab[data-view="${v}"]`)?.click();
  }, view);
  await page.waitForFunction(
    (v) => document.documentElement.getAttribute('data-init-view') === v,
    view,
    { timeout: 12000 },
  ).catch(() => {});
  await page.waitForTimeout(300);
}

function record(cases, entry) {
  cases.push(entry);
  const tag = entry.skipped ? 'SKIP' : entry.ok ? 'OK' : 'FAIL';
  const detail = entry.skipped
    ? entry.reason
    : entry.reason || (entry.gap != null ? `gap=${entry.gap}` : '');
  console.log(`  [${tag}] ${entry.viewport} ${entry.id} ${detail}`);
}

async function openModal(page, fnName, args = []) {
  return page.evaluate(
    async ({ fnName, args }) => {
      const g = window.__baklogModalGeom;
      const fn = g?.[fnName];
      if (typeof fn !== 'function') throw new Error(`missing ${fnName}`);
      return fn(...args);
    },
    { fnName, args },
  );
}

async function measureModal(page, modalId) {
  return page.evaluate((id) => window.__baklogModalGeom.measure(id), modalId);
}

async function closeModal(page, fnName) {
  await page.evaluate((name) => window.__baklogModalGeom?.[name]?.(), fnName);
  await page.waitForTimeout(80);
}

async function runModalCase(page, viewport, cases, spec) {
  try {
    if (spec.id === 'notes' || spec.id === 'addGame') {
      await clickViewTab(page, 'library');
      await page.waitForFunction(
        () => (window.__baklogDrillGeom?.visibleListKeys?.() || []).length > 0,
        null,
        { timeout: 15000 },
      ).catch(() => {});
    }

    const opened = await openModal(page, spec.open);
    if (spec.id === 'notes' && opened === false) {
      record(cases, {
        viewport: viewport.name,
        id: spec.id,
        skipped: true,
        reason: 'no-game-key',
      });
      return;
    }
    if (spec.id === 'addGame' && opened === false) {
      record(cases, {
        viewport: viewport.name,
        id: spec.id,
        skipped: true,
        reason: 'add-game-not-opened',
      });
      return;
    }

    await page.waitForTimeout(120);
    const result = await measureModal(page, spec.modalId);
    record(cases, {
      viewport: viewport.name,
      id: spec.id,
      modalId: spec.modalId,
      ...result,
    });
    await closeModal(page, spec.close);
  } catch (err) {
    record(cases, {
      viewport: viewport.name,
      id: spec.id,
      ok: false,
      reason: String(err?.message || err).slice(0, 200),
    });
    await closeModal(page, spec.close).catch(() => {});
  }
}

async function suiteForViewport(page, viewport, cases) {
  console.log(`\n== viewport ${viewport.name} ${viewport.width}x${viewport.height} ==`);
  for (const spec of MODALS) {
    await runModalCase(page, viewport, cases, spec);
  }
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  const report = {
    capturedAt: new Date().toISOString(),
    baseUrl: BASE,
    viewports: VIEWPORTS.map((v) => v.name),
    modals: MODALS.map((m) => m.id),
    cases: [],
    failures: [],
    skipped: 0,
  };

  try {
    for (const vp of VIEWPORTS) {
      const contextOpts = {
        viewport: { width: vp.width, height: vp.height },
        actionTimeout: 8000,
      };
      if (vp.isMobile) {
        contextOpts.isMobile = true;
        contextOpts.hasTouch = true;
        contextOpts.userAgent = devices['iPhone 12'].userAgent;
      }
      const context = await browser.newContext(contextOpts);
      const page = await context.newPage();
      page.setDefaultTimeout(8000);
      await page.addInitScript(() => {
        try {
          localStorage.setItem('baklog-perf', '1');
        } catch (_) { /* noop */ }
      });
      await page.goto(`${BASE}/?perf=1`, { waitUntil: 'domcontentloaded', timeout: 30000 });
      await waitBoot(page);

      const before = report.cases.length;
      await suiteForViewport(page, vp, report.cases);
      const slice = report.cases.slice(before);
      for (const c of slice) {
        if (c.skipped) report.skipped += 1;
        else if (!c.ok) {
          report.failures.push(`${c.viewport}:${c.id} ${c.reason || `gap=${c.gap}`}`);
        }
      }
      await context.close();
    }
  } finally {
    await browser.close();
  }

  fs.writeFileSync(OUT, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
  console.log(`\nWrote ${OUT}`);
  console.log(
    `cases=${report.cases.length} failures=${report.failures.length} skipped=${report.skipped}`,
  );
  if (report.failures.length) {
    console.error('HARD FAILURES:');
    for (const f of report.failures) console.error(`  ${f}`);
    process.exit(1);
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
