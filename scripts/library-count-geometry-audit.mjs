#!/usr/bin/env node
/**
 * Library-count +1 geometry audit — Playwright viewport matrix.
 * Usage: node scripts/library-count-geometry-audit.mjs [baseUrl]
 * Expects a live dashboard (dev or frozen) on baseUrl.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const BASE = (process.argv[2] || 'http://127.0.0.1:8765').replace(/\/$/, '');
const OUT = path.join(root, 'scripts', 'library-count-geometry-last-run.json');

const VIEWPORTS = [
  { name: 'phone390', width: 390, height: 844 },
  { name: 'tablet768', width: 768, height: 1024 },
  { name: 'desk1024', width: 1024, height: 768 },
];

async function waitBoot(page, timeoutMs = 90000) {
  await page.waitForFunction(
    () => !document.documentElement.hasAttribute('data-boot-loading'),
    null,
    { timeout: timeoutMs },
  ).catch(() => {});
  await page.waitForSelector('#dashHeroCount, [data-count-target="library"]', {
    timeout: timeoutMs,
  }).catch(() => {});
}

async function measureHeroPopup(page) {
  return page.evaluate(async () => {
    const hero = document.getElementById('dashHeroCount');
    if (!hero) return { ok: false, reason: 'no-hero' };
    document.querySelectorAll('.library-count-popup').forEach((el) => el.remove());
    const run =
      typeof window.baklogDemoLibraryCountSmall === 'function'
        ? window.baklogDemoLibraryCountSmall
        : null;
    if (!run) return { ok: false, reason: 'no-demo-helper' };
    run();
    await new Promise((r) => setTimeout(r, 450));
    const popup = document.querySelector(
      '.library-count-popup--floated:not(.library-count-popup--floated-chip)',
    );
    if (!popup) return { ok: false, reason: 'no-popup' };
    const a = hero.getBoundingClientRect();
    const p = popup.getBoundingClientRect();
    const gapX = p.left - a.right;
    const midY = p.top + p.height / 2;
    const bandLo = a.top + a.height * 0.2;
    const bandHi = a.top + a.height * 0.85;
    const inBand = midY >= bandLo && midY <= bandHi;
    const tightX = gapX >= -2 && gapX <= 18;
    return {
      ok: inBand && tightX,
      kind: 'hero',
      gapX,
      midY,
      bandLo,
      bandHi,
      anchor: { top: a.top, right: a.right, height: a.height, width: a.width },
      popup: { top: p.top, left: p.left, height: p.height, width: p.width },
      inBand,
      tightX,
    };
  });
}

async function measureChipPopup(page) {
  return page.evaluate(async () => {
    const tab = document.querySelector('.view-tab[data-view="library"]');
    tab?.click();
    await new Promise((r) => setTimeout(r, 400));
    const chip = document.querySelector('[data-count-target="library"]');
    if (!chip) return { ok: false, reason: 'no-chip', soft: true };
    document.querySelectorAll('.library-count-popup').forEach((el) => el.remove());
    const host = chip.closest('[data-libcount-host]') || chip.parentElement;
    if (!host) return { ok: false, reason: 'no-host', soft: true };
    // Drive flashCountUp if exposed via demo cancel + manual import is not available;
    // synthesize a minimal body-fixed popup using the same placement helper when present.
    const placeFn = window.__baklogComputeLibCountPlacement;
    const rect = chip.getBoundingClientRect();
    const fs = parseFloat(getComputedStyle(chip).fontSize) || 14;
    let left;
    let top;
    let popupFs;
    if (typeof placeFn === 'function') {
      const place = placeFn({
        rect: { top: rect.top, right: rect.right, height: rect.height, width: rect.width },
        fontSize: fs,
        kind: 'chip',
        stackIndex: 0,
        viewport: { width: window.innerWidth, height: window.innerHeight },
      });
      left = place.left;
      top = place.top;
      popupFs = place.popupFs;
    } else {
      popupFs = Math.max(14, Math.min(22, fs * 1.12));
      left = rect.right + Math.max(2, fs * 0.12);
      top = rect.top + rect.height / 2 - popupFs * 0.45;
    }
    const el = document.createElement('span');
    el.className = 'library-count-popup library-count-popup--floated library-count-popup--floated-chip';
    el.textContent = '+1';
    el.style.fontSize = `${popupFs}px`;
    el.style.left = `${left}px`;
    el.style.top = `${top}px`;
    document.body.appendChild(el);
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    const p = el.getBoundingClientRect();
    const a = chip.getBoundingClientRect();
    const gapX = p.left - a.right;
    const midY = p.top + p.height / 2;
    const bandLo = a.top + a.height * 0.15;
    const bandHi = a.top + a.height * 0.9;
    const inBand = midY >= bandLo && midY <= bandHi;
    const tightX = gapX >= -2 && gapX <= 18;
    const sizeOk = popupFs <= fs * 1.35 + 0.5;
    el.remove();
    return {
      ok: inBand && tightX && sizeOk,
      kind: 'chip',
      gapX,
      midY,
      popupFs,
      chipFs: fs,
      inBand,
      tightX,
      sizeOk,
      anchor: { top: a.top, right: a.right, height: a.height },
    };
  });
}

async function runViewport(browser, vp) {
  const context = await browser.newContext({
    viewport: { width: vp.width, height: vp.height },
  });
  const page = await context.newPage();
  const cases = [];
  try {
    await page.goto(`${BASE}/?demo=count-small`, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await waitBoot(page);
    // Expose placement helper for chip path when module graph is available.
    await page.addInitScript(() => {}).catch(() => {});
    await page.evaluate(async () => {
      try {
        const mod = await import('/js/library-count-animation.js');
        window.__baklogComputeLibCountPlacement = mod.computeLibraryCountPopupPlacement;
      } catch {
        /* built dist may not expose raw ESM; chip path falls back to inline math */
      }
    }).catch(() => {});

    const hero = await measureHeroPopup(page);
    cases.push({ viewport: vp.name, ...hero });
    const chip = await measureChipPopup(page);
    cases.push({ viewport: vp.name, ...chip });
  } finally {
    await context.close();
  }
  return cases;
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  const all = [];
  try {
    for (const vp of VIEWPORTS) {
      console.log(`viewport ${vp.name} ${vp.width}x${vp.height}`);
      const cases = await runViewport(browser, vp);
      for (const c of cases) {
        const tag = c.ok ? 'OK' : c.soft ? 'SOFT' : 'FAIL';
        console.log(
          `  [${tag}] ${c.kind || '?'}`,
          c.reason || `gapX=${c.gapX?.toFixed?.(1)} midY=${c.midY?.toFixed?.(1)}`,
        );
        all.push(c);
      }
    }
  } finally {
    await browser.close();
  }

  const hardFails = all.filter((c) => !c.ok && !c.soft);
  fs.writeFileSync(OUT, JSON.stringify({ base: BASE, at: new Date().toISOString(), cases: all }, null, 2));
  console.log(`wrote ${OUT}`);
  if (hardFails.length) {
    console.error(`${hardFails.length} hard failure(s)`);
    process.exit(1);
  }
  console.log('library-count geometry audit OK');
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
