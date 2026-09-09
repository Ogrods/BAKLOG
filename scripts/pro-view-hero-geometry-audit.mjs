#!/usr/bin/env node
/**
 * Back BAKLOG hero geometry — viewport matrix for beta (checkout closed) layout.
 * Usage: node scripts/pro-view-hero-geometry-audit.mjs [baseUrl]
 * Prefer: BAKLOG_AUTH_DISABLED=1 BAKLOG_PROFILE=perf
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';
import { clickViewTab, waitViewSettled } from './audit-view-click.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const BASE = process.argv[2] || 'http://127.0.0.1:8765';
const OUT = path.join(root, 'scripts', 'pro-view-hero-geometry-last-run.json');

const VIEWPORTS = [
  { width: 1280, height: 800, label: '1280' },
  { width: 1024, height: 768, label: '1024' },
  { width: 768, height: 1024, label: '768' },
  { width: 390, height: 844, label: '390' },
  { width: 360, height: 740, label: '360' },
  { width: 844, height: 390, label: '844x390' },
];

async function measureHero(page) {
  return page.evaluate(() => {
    const main = document.querySelector('.pro-view-hero-main');
    const copy = document.querySelector('.pro-view-hero-copy');
    const beta = document.querySelector('.pro-view-founder--hero-beta');
    const pricing = document.querySelector('.pro-view-hero .pro-view-pricing');
    const sub = document.querySelector('.pro-view-subhead');
    if (!main || !copy) {
      return { ok: false, error: 'missing hero nodes' };
    }
    const mr = main.getBoundingClientRect();
    const cr = copy.getBoundingClientRect();
    const br = beta?.getBoundingClientRect() || null;
    const pr = pricing?.getBoundingClientRect() || null;
    const sr = sub?.getBoundingClientRect() || null;
    const issues = [];
    if (pricing && !beta) {
      // Live checkout: pricing should not leave a huge empty mid gap on wide screens.
      const gap = pr.left - cr.right;
      if (gap > 120) issues.push(`checkout_side_gap_${Math.round(gap)}`);
    }
    if (beta) {
      if (pricing) issues.push('beta_still_has_pricing_column');
      if (!main.classList.contains('pro-view-hero-main--beta')) {
        issues.push('missing_beta_main_class');
      }
      if (!copy.contains(beta)) issues.push('beta_note_not_in_copy');
      if (sr && br.top < sr.bottom - 1) issues.push('beta_note_not_below_subhead');
      // Side-by-side regression: beta note should share copy column width, not sit far right.
      if (br.left > cr.left + 24) issues.push(`beta_note_inset_${Math.round(br.left - cr.left)}`);
      if (br.width > cr.width + 2) issues.push('beta_note_wider_than_copy');
      // Empty mid-gap heuristic from the old side-column layout.
      const rightSlack = mr.right - br.right;
      if (rightSlack > mr.width * 0.45 && br.width < mr.width * 0.4) {
        issues.push(`beta_right_slack_${Math.round(rightSlack)}`);
      }
    }
    const overflowPx = Math.max(
      0,
      Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) -
        document.documentElement.clientWidth,
    );
    if (overflowPx > 1) issues.push(`page_overflow_${overflowPx}`);
    return {
      ok: issues.length === 0,
      issues,
      main: { w: Math.round(mr.width), h: Math.round(mr.height) },
      copy: { w: Math.round(cr.width), h: Math.round(cr.height) },
      beta: br
        ? { w: Math.round(br.width), h: Math.round(br.height), top: Math.round(br.top) }
        : null,
      pricing: pr ? { w: Math.round(pr.width), left: Math.round(pr.left) } : null,
      overflowPx,
    };
  });
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  const results = [];
  try {
    for (const vp of VIEWPORTS) {
      const page = await browser.newPage({ viewport: { width: vp.width, height: vp.height } });
      await page.goto(BASE, { waitUntil: 'domcontentloaded', timeout: 30000 });
      await page.waitForFunction(
        () => !document.documentElement.hasAttribute('data-boot-loading'),
        null,
        { timeout: 25000 },
      );
      await clickViewTab(page, 'pro');
      await waitViewSettled(page, 'pro');
      await page.waitForSelector('.pro-view-hero-main', { timeout: 10000 });
      const m = await measureHero(page);
      results.push({ viewport: vp.label, ...m });
      await page.close();
    }
  } finally {
    await browser.close();
  }
  fs.writeFileSync(OUT, `${JSON.stringify({ base: BASE, results }, null, 2)}\n`);
  const failed = results.filter((r) => !r.ok);
  for (const r of results) {
    const mark = r.ok ? 'OK' : 'FAIL';
    console.log(
      `${mark} ${r.viewport}: copy=${r.copy?.w}px beta=${r.beta?.w ?? 'n/a'} overflow=${r.overflowPx}${
        r.issues?.length ? ` issues=${r.issues.join(',')}` : ''
      }`,
    );
  }
  if (failed.length) {
    console.error(`pro-view hero geometry FAIL (${failed.length}/${results.length})`);
    process.exit(1);
  }
  console.log('pro-view hero geometry audit OK');
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
