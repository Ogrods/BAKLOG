#!/usr/bin/env node
/**
 * Drill geometry audit — Playwright matrix of row/toolbar landings.
 * Usage: node scripts/drill-geometry-audit.mjs [baseUrl]
 * Requires: live server with BAKLOG_PROFILE=perf (see start-drill-geometry.ps1).
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium, devices } from 'playwright';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const BASE = process.argv[2] || 'http://127.0.0.1:8765';
const OUT = path.join(root, 'scripts', 'drill-geometry-last-run.json');

const VIEWPORTS = [
  { name: 'phone360', width: 360, height: 740 },
  { name: 'phone390', width: 390, height: 844 },
  { name: 'phoneMQ', width: 639, height: 800 },
  { name: 'mid640', width: 640, height: 800 },
  { name: 'tablet768', width: 768, height: 1024 },
  { name: 'mid1024', width: 1024, height: 768 },
  { name: 'desk1280', width: 1280, height: 800 },
  { name: 'desk1440', width: 1440, height: 900 },
  {
    name: 'shortLand',
    width: 800,
    height: 480,
    isMobile: true,
    hasTouch: true,
  },
];

async function waitBoot(page, timeoutMs = 60000) {
  await page.waitForFunction(
    () => !document.documentElement.hasAttribute('data-boot-loading'),
    null,
    { timeout: timeoutMs },
  );
  await page.waitForFunction(
    () => !!window.__baklogDrillGeom?.waitForIdle,
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
  await waitIdle(page);
}

async function waitIdle(page) {
  return page.evaluate(async () => {
    const g = window.__baklogDrillGeom;
    if (!g?.waitForIdle) return false;
    if (g.hasPendingScrollTarget?.()) g.scheduleScrollAfterChromeSettled?.();
    return g.waitForIdle({ timeoutMs: 10000 });
  });
}

async function measureRow(page, key) {
  return page.evaluate((k) => window.__baklogDrillGeom.measureRow(k), key);
}

async function measureToolbar(page) {
  return page.evaluate(() => window.__baklogDrillGeom.measureToolbar());
}

async function focusKey(page, key) {
  await page.evaluate((k) => window.__baklogDrillGeom.focusGame(k), key);
  await waitIdle(page);
  await page.evaluate(async (k) => {
    const g = window.__baklogDrillGeom;
    for (let i = 0; i < 4; i++) {
      const m = g.measureRow(k);
      if (m.ok || m.reason === 'row-missing') return;
      g.scrollRowIntoAim?.(k);
      await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
      await new Promise((r) => setTimeout(r, 90));
    }
  }, key);
  const m = await measureRow(page, key);
  if (m?.reason === 'row-missing') return { skipped: true, reason: 'row-missing' };
  return m;
}

function record(cases, entry) {
  cases.push(entry);
  const tag = entry.skipped
    ? 'SKIP'
    : entry.ok
      ? 'OK'
      : entry.soft
        ? 'SOFT'
        : 'FAIL';
  const detail = entry.skipped
    ? entry.reason
    : entry.delta != null
      ? `delta=${entry.delta}`
      : entry.reason || '';
  console.log(`  [${tag}] ${entry.viewport} ${entry.id} ${detail}`);
}

async function runCase(page, viewport, id, fn) {
  try {
    const result = await fn();
    if (result?.skipped) {
      record(viewport._cases, {
        viewport: viewport.name,
        id,
        skipped: true,
        reason: result.reason,
        soft: !!result.soft,
      });
      return;
    }
    record(viewport._cases, {
      viewport: viewport.name,
      id,
      soft: !!result.soft,
      ...result,
    });
  } catch (err) {
    record(viewport._cases, {
      viewport: viewport.name,
      id,
      ok: false,
      reason: String(err?.message || err).slice(0, 200),
    });
  }
}

async function ensureHouseStripe(page) {
  await page.evaluate(() => {
    const slot = document.getElementById('viewHouseSlot');
    if (!slot) return;
    slot.classList.remove('hidden');
    if (!slot.innerHTML.trim()) {
      slot.innerHTML =
        '<div class="house-stripe-card house-stripe-card--lib" style="min-height:72px;padding:12px">geometry audit house stripe</div>';
    }
  });
}

async function queryKey(page, selector) {
  return page.evaluate((sel) => {
    const el = document.querySelector(sel);
    return el?.dataset?.key || el?.dataset?.gameKey || null;
  }, selector);
}

async function runToolbarDrill(page, fnName, args = []) {
  await page.evaluate(
    ({ fnName, args }) => {
      const g = window.__baklogDrillGeom;
      const fn = g[fnName];
      if (typeof fn !== 'function') throw new Error(`missing ${fnName}`);
      fn(...args);
      g.scheduleScrollAfterChromeSettled?.();
    },
    { fnName, args },
  );
  await waitIdle(page);
  const scrollMeta = await page.evaluate(async () => {
    const g = window.__baklogDrillGeom;
    const n = g.visibleListKeys?.()?.length || 0;
    const maxScroll = document.documentElement.scrollHeight - window.innerHeight;
    for (let i = 0; i < 3; i++) {
      const m = g.measureToolbar();
      if (m.ok) return { n, maxScroll, m };
      if (maxScroll < 24) break;
      g.scrollToToolbar?.();
      await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
      await new Promise((r) => setTimeout(r, 80));
    }
    return { n, maxScroll, m: g.measureToolbar() };
  });
  if (scrollMeta.n === 0) {
    return { skipped: true, reason: 'empty-filter-list' };
  }
  // Short filtered lists cannot move the toolbar under sticky chrome.
  if (!scrollMeta.m?.ok && scrollMeta.maxScroll < Math.max(24, (scrollMeta.m?.delta || 0) - 8)) {
    return { skipped: true, reason: 'no-scroll-room' };
  }
  return scrollMeta.m;
}

async function suiteForViewport(page, viewport, cases) {
  viewport._cases = cases;

  await clickViewTab(page, 'dashboard');
  await page.waitForTimeout(500);

  await runCase(page, viewport, 'row.dashVersus', async () => {
    const key = await queryKey(page, '#dashPicksVersusCard [data-action="dash-list-jump"][data-key]');
    if (!key) return { skipped: true, reason: 'no-versus-row' };
    return focusKey(page, key);
  });

  await clickViewTab(page, 'dashboard');
  await runCase(page, viewport, 'row.dashRecent', async () => {
    const key = await queryKey(page, '#dashRecentAdditions [data-action="dash-list-jump"][data-key]');
    if (!key) return { skipped: true, reason: 'no-recent-row' };
    return focusKey(page, key);
  });

  await clickViewTab(page, 'dashboard');
  await runCase(page, viewport, 'row.dashItch', async () => {
    const key = await queryKey(
      page,
      '#dashItchCard [data-action="dash-list-jump"][data-key], .itch-hero-card[data-key]',
    );
    if (!key) return { skipped: true, reason: 'no-itch-hero' };
    return focusKey(page, key);
  });

  await clickViewTab(page, 'dashboard');
  await runCase(page, viewport, 'row.spotlight', async () => {
    const key = await page.evaluate(() => {
      const el = document.querySelector('#dashboardSpotlight[data-action="dash-list-jump"][data-key]');
      return el?.dataset?.key || null;
    });
    if (!key) return { skipped: true, reason: 'no-spotlight-jump' };
    return focusKey(page, key);
  });

  await clickViewTab(page, 'dashboard');
  await runCase(page, viewport, 'row.coopPick', async () => {
    const key = await queryKey(page, '[data-action="coop-pick-jump"][data-key]');
    if (!key) return { skipped: true, reason: 'no-coop-pick' };
    return focusKey(page, key);
  });

  await clickViewTab(page, 'library');
  await waitIdle(page);

  await runCase(page, viewport, 'row.pickCard', async () => {
    const key = await queryKey(page, '#picksGrid .pick-card[data-game-key]:not(.sponsored-pick-card)');
    if (!key) return { skipped: true, reason: 'no-pick-card' };
    return focusKey(page, key);
  });

  await runCase(page, viewport, 'row.pickForMe', async () => {
    const key = await page.evaluate(() => {
      const btn = document.getElementById('pickForMe');
      if (!btn) return null;
      btn.click();
      return true;
    });
    if (!key) return { skipped: true, reason: 'no-pick-for-me' };
    await waitIdle(page);
    const picked = await page.evaluate(() => window.__baklogDrillGeom.pickedKey());
    if (!picked) return { skipped: true, reason: 'pick-for-me-no-key' };
    return focusKey(page, picked);
  });

  await runCase(page, viewport, 'row.focusDeep', async () => {
    const key = await page.evaluate(() => {
      const keys = window.__baklogDrillGeom.visibleListKeys();
      if (keys.length < 60) return null;
      return keys[Math.min(keys.length - 5, 80)];
    });
    if (!key) return { skipped: true, reason: 'list-too-short' };
    return focusKey(page, key);
  });

  await runCase(page, viewport, 'row.keyboard', async () => {
    const key = await page.evaluate(() => {
      const keys = window.__baklogDrillGeom.visibleListKeys();
      if (keys.length < 40) return null;
      const idx = Math.floor(keys.length / 2);
      window.__baklogDrillGeom.scrollToRowIndex(idx, { smooth: false });
      return keys[idx];
    });
    if (!key) return { skipped: true, reason: 'list-too-short' };
    await waitIdle(page);
    return measureRow(page, key);
  });

  await runCase(page, viewport, 'row.alpha', async () => {
    const key = await page.evaluate(() => {
      const btn = document.querySelector('.alpha-nav-btn.enabled:not([disabled])');
      if (!btn) return null;
      btn.click();
      return window.__baklogDrillGeom.pickedKey();
    });
    if (!key) return { skipped: true, reason: 'no-alpha-btn' };
    await waitIdle(page);
    return measureRow(page, key);
  });

  await runCase(page, viewport, 'row.flash', async () => {
    const key = await page.evaluate(() => {
      const keys = window.__baklogDrillGeom.visibleListKeys();
      return keys[Math.min(25, keys.length - 1)] || null;
    });
    if (!key) return { skipped: true, reason: 'no-keys' };
    await page.evaluate((k) => window.__baklogDrillGeom.flashGameRow(k), key);
    await waitIdle(page);
    return measureRow(page, key);
  });

  await runCase(page, viewport, 'row.scatterHit', async () => {
    const key = await page.evaluate(() => {
      const keys = window.__baklogDrillGeom.visibleListKeys();
      return keys[10] || keys[0] || null;
    });
    if (!key) return { skipped: true, reason: 'no-keys' };
    return focusKey(page, key);
  });

  await clickViewTab(page, 'dashboard');
  await runCase(page, viewport, 'row.scatterList', async () => {
    const key = await page.evaluate(() => {
      const els = [...document.querySelectorAll('[data-action="dash-list-jump"][data-key]')];
      return els[1]?.dataset?.key || els[0]?.dataset?.key || null;
    });
    if (!key) return { skipped: true, reason: 'no-scatter-list' };
    return focusKey(page, key);
  });

  await clickViewTab(page, 'wishlist');
  await waitIdle(page);
  await runCase(page, viewport, 'row.dealSteal', async () => {
    const key = await queryKey(page, '[data-action="deal-steal-jump"][data-key]');
    if (!key) return { skipped: true, reason: 'no-steal-rows' };
    return focusKey(page, key);
  });

  await runCase(page, viewport, 'row.dealHero', async () => {
    const key = await queryKey(page, '[data-action="deal-hero"][data-key]');
    if (!key) return { skipped: true, reason: 'no-deal-hero' };
    return focusKey(page, key);
  });

  await clickViewTab(page, 'dashboard');
  await page.waitForTimeout(300);

  const toolbarCases = [
    // Personal status defaults to backlog when personal.json is empty.
    ['tb.store', 'dashDrillStore', ['steam']],
    ['tb.status', 'dashDrillStatus', ['backlog']],
    ['tb.storeStatus', 'dashDrillStoreStatus', ['steam', 'backlog']],
    ['tb.genre', 'dashDrillGenre', ['Action']],
    ['tb.hltb', 'dashDrillHltbBucket', [0]],
    ['tb.rating', 'dashDrillMinRating', [80]],
    ['tb.coop', 'dashDrillCoop', [{ online: true }]],
    ['tb.itchGenre', 'dashDrillItchGenre', ['Action']],
  ];

  for (const [id, fnName, args] of toolbarCases) {
    await clickViewTab(page, 'dashboard');
    await runCase(page, viewport, id, async () => runToolbarDrill(page, fnName, args));
  }

  await clickViewTab(page, 'dashboard');
  await runCase(page, viewport, 'tb.wishDealOnSale', async () => {
    await page.evaluate(async () => {
      const g = window.__baklogDrillGeom;
      const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
      // Auth polls can briefly clear ITAD; re-stub until wishlist rows appear.
      for (let i = 0; i < 8; i++) {
        await g.stubItadConnected?.();
        g.drillWishlistDealFilter({ onSaleOnly: true });
        g.setPendingToolbar?.();
        g.scheduleScrollAfterChromeSettled?.();
        await g.waitForIdle?.({ timeoutMs: 2500 });
        if ((g.visibleListKeys?.() || []).length > 0) break;
        await sleep(250);
      }
    });
    const view = await page.evaluate(() => window.__baklogDrillGeom.activeView());
    if (view !== 'wishlist') return { skipped: true, reason: `view=${view}` };
    const scrollMeta = await page.evaluate(async () => {
      const g = window.__baklogDrillGeom;
      const n = g.visibleListKeys?.()?.length || 0;
      let maxScroll = document.documentElement.scrollHeight - window.innerHeight;
      for (let i = 0; i < 3; i++) {
        const m = g.measureToolbar();
        if (m.ok) return { n, maxScroll, m };
        if (maxScroll < 24) break;
        g.scrollToToolbar?.();
        await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
        await new Promise((r) => setTimeout(r, 80));
      }
      maxScroll = document.documentElement.scrollHeight - window.innerHeight;
      return { n, maxScroll, m: g.measureToolbar() };
    });
    if (scrollMeta.n === 0) {
      return { skipped: true, reason: 'empty-deal-filter' };
    }
    if (!scrollMeta.m?.ok && scrollMeta.maxScroll < Math.max(24, (scrollMeta.m?.delta || 0) - 8)) {
      return { skipped: true, reason: 'no-scroll-room' };
    }
    return scrollMeta.m;
  });

  await clickViewTab(page, 'dashboard');
  await runCase(page, viewport, 'tb.wishDealSteals', async () => {
    await page.evaluate(async () => {
      await window.__baklogDrillGeom?.stubItadConnected?.();
    });
    await page.waitForTimeout(200);
    const has = await page.evaluate(() => !!document.querySelector('[data-action="deal-steals"]'));
    if (!has) return { skipped: true, reason: 'no-deal-steals-btn' };
    await page.evaluate(() => {
      document.querySelector('[data-action="deal-steals"]')?.click();
      window.__baklogDrillGeom.setPendingToolbar?.();
      window.__baklogDrillGeom.scheduleScrollAfterChromeSettled?.();
    });
    await waitIdle(page);
    await page.waitForFunction(
      () => (window.__baklogDrillGeom.visibleListKeys?.() || []).length > 0,
      null,
      { timeout: 8000 },
    ).catch(() => {});
    const scrollMeta = await page.evaluate(async () => {
      const g = window.__baklogDrillGeom;
      const n = g.visibleListKeys?.()?.length || 0;
      const maxScroll = document.documentElement.scrollHeight - window.innerHeight;
      for (let i = 0; i < 3; i++) {
        const m = g.measureToolbar();
        if (m.ok) return { n, maxScroll, m };
        if (maxScroll < 24) break;
        g.scrollToToolbar?.();
        await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
        await new Promise((r) => setTimeout(r, 80));
      }
      return { n, maxScroll: document.documentElement.scrollHeight - window.innerHeight, m: g.measureToolbar() };
    });
    if (scrollMeta.n === 0) return { skipped: true, reason: 'empty-steals-filter' };
    if (!scrollMeta.m?.ok && scrollMeta.maxScroll < Math.max(24, (scrollMeta.m?.delta || 0) - 8)) {
      return { skipped: true, reason: 'no-scroll-room' };
    }
    return scrollMeta.m;
  });

  await runCase(page, viewport, 'periph.itchCard', async () => {
    await clickViewTab(page, 'itch');
    await waitIdle(page);
    return page.evaluate(() => {
      const el = document.getElementById('dashItchCard');
      if (!el) return { ok: false, reason: 'missing', soft: true };
      const top = el.getBoundingClientRect().top;
      const ok = top >= -20 && top <= window.innerHeight;
      return { ok, soft: true, delta: Math.round(Math.abs(top) * 10) / 10, toolbarTop: Math.round(top) };
    });
  });

  await runCase(page, viewport, 'periph.claims', async () => {
    await clickViewTab(page, 'dashboard');
    const clicked = await page.evaluate(() => {
      const mod = document.getElementById('claimableNowModule');
      if (mod && typeof mod.scrollIntoView === 'function') {
        mod.scrollIntoView({ behavior: 'instant', block: 'start' });
        return true;
      }
      return false;
    });
    if (!clicked) return { skipped: true, reason: 'no-claims-module', soft: true };
    await page.waitForTimeout(300);
    return page.evaluate(() => {
      const el = document.getElementById('claimableNowModule');
      if (!el) return { ok: false, reason: 'missing', soft: true };
      const top = el.getBoundingClientRect().top;
      const ok = top >= -40 && top < window.innerHeight;
      return { ok, soft: true, delta: Math.round(Math.abs(top) * 10) / 10, toolbarTop: Math.round(top) };
    });
  });

  if (viewport.name === 'desk1280' || viewport.name === 'phone390') {
    await ensureHouseStripe(page);
    await clickViewTab(page, 'dashboard');
    await runCase(page, viewport, 'tb.store+house', async () => {
      await ensureHouseStripe(page);
      return runToolbarDrill(page, 'dashDrillStore', ['steam']);
    });
    await runCase(page, viewport, 'row.focusDeep+house', async () => {
      await clickViewTab(page, 'library');
      await ensureHouseStripe(page);
      const key = await page.evaluate(() => {
        const keys = window.__baklogDrillGeom.visibleListKeys();
        return keys[Math.min(70, keys.length - 1)] || null;
      });
      if (!key) return { skipped: true, reason: 'no-keys' };
      return focusKey(page, key);
    });
  }
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  const report = {
    capturedAt: new Date().toISOString(),
    baseUrl: BASE,
    viewports: VIEWPORTS.map((v) => v.name),
    cases: [],
    failures: [],
    softFailures: [],
    skipped: 0,
  };

  try {
    for (const vp of VIEWPORTS) {
      console.log(`\n== viewport ${vp.name} ${vp.width}x${vp.height} ==`);
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
      // After auth status settles, pretend ITAD is connected for deal drills.
      await page.waitForTimeout(600);
      await page.evaluate(async () => {
        await window.__baklogDrillGeom?.stubItadConnected?.();
      });

      const before = report.cases.length;
      await suiteForViewport(page, vp, report.cases);
      const slice = report.cases.slice(before);
      for (const c of slice) {
        if (c.skipped) report.skipped += 1;
        else if (!c.ok && c.soft) report.softFailures.push(`${c.viewport}:${c.id}`);
        else if (!c.ok) report.failures.push(`${c.viewport}:${c.id} ${c.reason || `delta=${c.delta}`}`);
      }
      await context.close();
    }
  } finally {
    await browser.close();
  }

  fs.writeFileSync(OUT, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
  console.log(`\nWrote ${OUT}`);
  console.log(
    `cases=${report.cases.length} failures=${report.failures.length} soft=${report.softFailures.length} skipped=${report.skipped}`,
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
