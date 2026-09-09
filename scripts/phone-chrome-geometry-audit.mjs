#!/usr/bin/env node
/**
 * Phone chrome light checks — 390x844 (iPhone 12 Pro-ish).
 * Usage: node scripts/phone-chrome-geometry-audit.mjs [baseUrl]
 * Prefer: BAKLOG_AUTH_DISABLED=1
 */
import { chromium } from 'playwright';
import { clickViewTab, waitViewSettled } from './audit-view-click.mjs';

const BASE = process.argv[2] || 'http://127.0.0.1:8765';
const VP = { width: 390, height: 844 };

async function main() {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: VP });
  const issues = [];
  try {
    await page.goto(BASE, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForFunction(
      () => !document.documentElement.hasAttribute('data-boot-loading'),
      null,
      { timeout: 30000 },
    );

    const gutter = await page.evaluate(() =>
      getComputedStyle(document.documentElement).scrollbarGutter,
    );
    if (gutter && gutter !== 'auto' && gutter !== 'stable') {
      // auto is expected on phone; stable would recreate the stripe
    }
    if (gutter === 'stable') issues.push(`scrollbar_gutter_stable`);

    await clickViewTab(page, 'library');
    await waitViewSettled(page, 'library');
    await page.waitForSelector('#alphaNav', { timeout: 10000 });

    const alpha = await page.evaluate(() => {
      const nav = document.getElementById('alphaNav');
      const wrap = document.getElementById('alphaNavWrap');
      if (!nav || !wrap) return { ok: false, error: 'missing alpha' };
      const nr = nav.getBoundingClientRect();
      const wr = wrap.getBoundingClientRect();
      const h = window.innerHeight;
      const problems = [];
      if (nr.bottom > h + 1) problems.push(`alpha_nav_bottom_${Math.round(nr.bottom)}_gt_${h}`);
      if (wr.bottom > h + 1) problems.push(`alpha_wrap_bottom_${Math.round(wr.bottom)}_gt_${h}`);
      return {
        ok: problems.length === 0,
        problems,
        navBottom: Math.round(nr.bottom),
        wrapBottom: Math.round(wr.bottom),
        maxH: getComputedStyle(nav).maxHeight,
        gutter: getComputedStyle(document.documentElement).scrollbarGutter,
      };
    });
    if (!alpha.ok) issues.push(...(alpha.problems || [alpha.error]));

    // Tab-switch overlay: center of card should sit mid content band.
    await page.evaluate(() => {
      const ov = document.getElementById('viewLoadingOverlay');
      const header = document.querySelector('.app-header');
      const top = header ? Math.ceil(header.getBoundingClientRect().bottom) : 0;
      if (ov) {
        ov.style.setProperty('--view-overlay-top', `${top}px`);
        ov.classList.add('show');
        ov.setAttribute('aria-hidden', 'false');
      }
    });
    await page.waitForTimeout(50);
    const load = await page.evaluate(() => {
      const ov = document.getElementById('viewLoadingOverlay');
      const card =
        ov?.querySelector('.app-view-overlay-card') ||
        ov?.querySelector('[class*="overlay-card"]');
      if (!ov || !card) return { ok: false, error: 'missing overlay card' };
      const or = ov.getBoundingClientRect();
      const cr = card.getBoundingClientRect();
      const mid = (cr.top + cr.bottom) / 2;
      const bandTop = or.top;
      const bandBot = or.bottom;
      const pct = (mid - bandTop) / Math.max(1, bandBot - bandTop);
      const problems = [];
      if (or.height > window.innerHeight + 2) {
        problems.push(`overlay_taller_than_vv_${Math.round(or.height)}`);
      }
      if (pct < 0.35 || pct > 0.65) {
        problems.push(`card_center_pct_${pct.toFixed(2)}`);
      }
      return {
        ok: problems.length === 0,
        problems,
        pct: Number(pct.toFixed(3)),
        ovH: Math.round(or.height),
        innerH: window.innerHeight,
      };
    });
    await page.evaluate(() => {
      document.getElementById('viewLoadingOverlay')?.classList.remove('show');
    });
    if (!load.ok) issues.push(...(load.problems || [load.error]));

    console.log(JSON.stringify({ alpha, load, gutter }, null, 2));
    if (issues.length) {
      console.error('FAIL', issues.join(', '));
      process.exit(1);
    }
    console.log('phone chrome geometry OK');
  } finally {
    await browser.close();
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
