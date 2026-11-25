#!/usr/bin/env node
/**
 * Capture README / social screenshots with Playwright.
 *
 * Expects a server already running against the fictional demo profile
 * (scripts/capture-screenshots.ps1 wires that up). Reduced motion is forced so
 * the spotlight, marquee, and count-up animations settle before each shot.
 *
 * Usage: node scripts/capture-screenshots.mjs [baseUrl] [--views a,b,c] [--dpr 1|2]
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const outDir = path.join(root, 'assets', 'screenshots');

const args = process.argv.slice(2);
const baseUrl = (args.find((a) => a.startsWith('http')) || 'http://127.0.0.1:8766').replace(/\/$/, '');
const viewsArg = args.indexOf('--views');
const views = (viewsArg > -1 && args[viewsArg + 1] ? args[viewsArg + 1] : 'dashboard,library,wishlist,connections')
  .split(',')
  .map((v) => v.trim())
  .filter(Boolean);
const dprArg = args.indexOf('--dpr');
const deviceScaleFactor = Math.max(1, Math.min(3, Number(dprArg > -1 && args[dprArg + 1] ? args[dprArg + 1] : 1) || 1));

// Each view needs a different "the page has actually painted" signal.
// `fetchers` seeds the dashboard tab then opens the fetches-log popover.
const READY = {
  dashboard: '#dashboardPicksRow',
  fetchers: '#dashboardPicksRow',
  library: '#tbody tr',
  wishlist: '#tbody tr',
  deals: '#tbody tr',
  itch: '#tbody tr',
  connections: '#connRail *',
};

function sessionViewFor(view) {
  return view === 'fetchers' ? 'dashboard' : view;
}

async function pingServer() {
  const res = await fetch(`${baseUrl}/api/config`);
  if (!res.ok) throw new Error(`config ${res.status}`);
}

// The active tab lives in profile-scoped sessionStorage (js/profiles.js
// activeViewSessionKey); prefs copies are deliberately dropped on load, so
// seeding that key is the only way to open a capture on a given tab.
const activeProfile = await fetch(`${baseUrl}/api/profiles`)
  .then((r) => r.json())
  .then((d) => d.active || 'default');
const profileSuffix = activeProfile && activeProfile !== 'default' ? `:${activeProfile}` : '';

fs.mkdirSync(outDir, { recursive: true });

// A capture server that ever refreshes a store would replace the fictional
// catalogs with this machine's real library, so verify what is being served
// before anything is written to disk.
const manifestPath = path.join(process.env.BAKLOG_DATA_DIR || '', 'demo-manifest.json');
if (fs.existsSync(manifestPath)) {
  const { expected } = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
  for (const [file, count] of Object.entries(expected)) {
    const res = await fetch(`${baseUrl}/${file}`);
    const served = (await res.json()).game_count;
    if (served !== count) {
      throw new Error(
        `${file} served ${served} rows, expected ${count}. The capture profile looks contaminated by real library data; regenerate it and check that auto-fetch is off.`,
      );
    }
  }
  console.log('[capture] demo catalogs verified fictional');
} else {
  console.warn(`[capture] no demo-manifest.json at ${manifestPath}; skipping contamination check`);
}

console.log(`[capture] viewport 1600x1000 @ dpr ${deviceScaleFactor}`);

const browser = await chromium.launch();
try {
  // One context for the whole run so we do not thrash the capture server
  // between views (separate contexts were leaving the port refused mid-run).
  const firstSeed = sessionViewFor(views[0] || 'dashboard');
  const context = await browser.newContext({
    viewport: { width: 1600, height: 1000 },
    deviceScaleFactor,
    reducedMotion: 'reduce',
    colorScheme: 'dark',
  });
  await context.addInitScript(({ wanted, profile, suffix }) => {
    localStorage.setItem('baklog-active-profile', profile);
    sessionStorage.setItem(`steam-backlog-ui-prefs:activeView${suffix}`, wanted);
    localStorage.setItem('baklog-color-theme', 'default');
    sessionStorage.setItem('baklog.runtimeModeBannerDismissed', '1');
  }, { wanted: firstSeed, profile: activeProfile, suffix: profileSuffix });

  const page = await context.newPage();
  await page.goto(`${baseUrl}/`, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle').catch(() => {});
  await page.waitForTimeout(800);

  for (const view of views) {
    await pingServer();

    const seedView = sessionViewFor(view);
    // Switch tabs via the nav button when possible (keeps one live document).
    const nav = page.locator(`[data-view="${seedView}"]`).first();
    if (await nav.count()) {
      await nav.click();
    } else {
      await page.evaluate(({ wanted, suffix }) => {
        sessionStorage.setItem(`steam-backlog-ui-prefs:activeView${suffix}`, wanted);
        location.reload();
      }, { wanted: seedView, suffix: profileSuffix });
      await page.waitForLoadState('domcontentloaded');
    }

    try {
      await page.waitForSelector(READY[view] || 'body', { timeout: 30000 });
    } catch {
      console.warn(`[capture] ${view}: ready selector never appeared, shooting anyway`);
    }
    await page.waitForLoadState('networkidle').catch(() => {});
    await page.waitForTimeout(900);

    // Close any leftover fetcher popover before non-fetchers shots.
    if (view !== 'fetchers') {
      await page.evaluate(() => {
        const pop = document.getElementById('fetcherPopover');
        const pill = document.getElementById('fetcherGlobalStatus');
        if (pop && !pop.hidden && pill) pill.click();
      }).catch(() => {});
    }

    if (view === 'fetchers') {
      try {
        // Ensure dashboard is painted, then open the fetches log.
        const pill = page.locator('#fetcherGlobalStatus');
        await pill.waitFor({ state: 'visible', timeout: 10000 });
        const expanded = await pill.getAttribute('aria-expanded');
        if (expanded !== 'true') await pill.click();
        await page.waitForSelector('#fetcherPopover:not([hidden])', { timeout: 10000 });
        await page.waitForTimeout(600);
      } catch (err) {
        console.warn(`[capture] fetchers: could not open popover (${err.message}); shooting dashboard anyway`);
      }
    }

    const out = path.join(outDir, `${view}.png`);
    await page.screenshot({ path: out });
    console.log(`Wrote ${path.relative(root, out)} (${fs.statSync(out).size} bytes)`);
  }

  await context.close();
} finally {
  await browser.close();
}
