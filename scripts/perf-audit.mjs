#!/usr/bin/env node
/**
 * Runtime perf audit against a live BAKLOG server (built mode + perf profile).
 * Usage: node scripts/perf-audit.mjs [baseUrl]
 * Requires: server on 8765 with BAKLOG_PROFILE=perf (see start-perf-server.ps1).
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const budget = JSON.parse(fs.readFileSync(path.join(root, 'perf-budget.json'), 'utf8'));
const BASE = process.argv[2] || 'http://127.0.0.1:8765';
const PERF_QUERY = '?perf=1';

const TAB_TRANSITIONS = [
  ['dashboard', 'library'],
  ['library', 'wishlist'],
  ['library', 'connections'],
  ['connections', 'dashboard'],
];

async function clickViewTab(page, view) {
  await page.evaluate((v) => {
    document.querySelector(`.view-tab[data-view="${v}"]`)?.click();
  }, view);
}

async function waitBootCurtainLift(page, timeoutMs = 15000) {
  const t0 = Date.now();
  await page.waitForFunction(
    () => !document.documentElement.hasAttribute('data-boot-loading'),
    null,
    { timeout: timeoutMs },
  );
  return Date.now() - t0;
}

async function waitViewSettled(page, view, timeoutMs = 12000) {
  const t0 = Date.now();
  await page.waitForFunction(
    ({ view, timeoutMs }) => {
      const overlay = !!document.getElementById('viewLoadingOverlay')?.classList.contains('show');
      const active = document.documentElement.getAttribute('data-init-view');
      return !overlay && active === view;
    },
    { view, timeoutMs },
    { timeout: timeoutMs },
  );
  return Date.now() - t0;
}

async function sampleTabSwitch(page, from, to) {
  await clickViewTab(page, from);
  await page.waitForFunction(
    (v) => document.documentElement.getAttribute('data-init-view') === v,
    from,
    { timeout: 10000 },
  );
  await page.waitForTimeout(300);
  const t0 = Date.now();
  await clickViewTab(page, to);
  const ms = await waitViewSettled(page, to);
  return { from, to, ms: Math.max(ms, Date.now() - t0) };
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  const report = {
    capturedAt: new Date().toISOString(),
    baseUrl: BASE,
    results: {},
    failures: [],
  };

  try {
    await page.addInitScript(() => {
      try { localStorage.setItem('baklog-perf', '1'); } catch (_) { /* noop */ }
    });

    const navStart = Date.now();
    await page.goto(`${BASE}/${PERF_QUERY}`, { waitUntil: 'domcontentloaded', timeout: 20000 });
    const bootMs = await waitBootCurtainLift(page);
    report.results.bootCurtainLiftMs = bootMs;
    if (bootMs > budget.bootCurtainLiftMs) {
      report.failures.push(`boot curtain lift ${bootMs}ms > ${budget.bootCurtainLiftMs}ms`);
    }

    await page.waitForFunction(
      () => window.__baklogBootPerf?.last?.totalMs != null,
      null,
      { timeout: 5000 },
    ).catch(() => {});

    await clickViewTab(page, 'library');
    await waitViewSettled(page, 'library');
    const tableRows = await page.evaluate(() =>
      document.querySelectorAll('#tbody tr:not(.virtual-spacer)').length,
    );
    report.results.libraryTableRows = tableRows;

    for (const [from, to] of TAB_TRANSITIONS) {
      const sample = await sampleTabSwitch(page, from, to);
      const key = `${from}->${to}`;
      report.results[`tabSwitchMs:${key}`] = sample.ms;
      const ceiling = budget.tabSwitchMs[to];
      if (ceiling != null && sample.ms > ceiling) {
        report.failures.push(`tab ${key} ${sample.ms}ms > ${ceiling}ms`);
      }
    }

    await clickViewTab(page, 'dashboard');
    await waitViewSettled(page, 'dashboard');
    await page.waitForTimeout(2500);
    const chartPerf = await page.evaluate(() => window.__baklogChartPerf?.last || null);
    if (chartPerf?.totalMs != null) {
      report.results.chartTotalMs = chartPerf.totalMs;
      if (chartPerf.totalMs > budget.chartTotalMs) {
        report.failures.push(`chart total ${chartPerf.totalMs}ms > ${budget.chartTotalMs}ms`);
      }
    }
    if (chartPerf?.frames?.janky != null) {
      report.results.chartJankyFrames = chartPerf.frames.janky;
      if (chartPerf.frames.janky > budget.chartJankyFrames) {
        report.failures.push(`chart janky frames ${chartPerf.frames.janky} > ${budget.chartJankyFrames}`);
      }
    }

    report.bootPerf = await page.evaluate(() => window.__baklogBootPerf?.last || null);
  } finally {
    await browser.close();
  }

  const outPath = path.join(root, 'scripts', 'perf-last-run.json');
  fs.writeFileSync(outPath, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
  console.log(JSON.stringify(report.results, null, 2));
  if (report.failures.length) {
    console.error('Perf audit failures:');
    for (const f of report.failures) console.error(`  - ${f}`);
    process.exit(1);
  }
  console.log(`Perf audit passed. Report: ${path.relative(root, outPath)}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
