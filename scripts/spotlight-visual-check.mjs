/**
 * Pixel-diff guard for landing .dash-mega spotlight layouts.
 * Run before editing landing/demo.css or landing/demo.js.
 *
 *   npm run check:spotlight:baseline   # capture reference PNGs
 *   npm run check:spotlight            # capture + diff against baseline
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import { PNG } from "pngjs";
import pixelmatch from "pixelmatch";

const root = path.resolve(import.meta.dirname, "..");
const landingHtml = path.join(root, "landing", "index.html");
const baselineDir = path.join(root, "tmp", "spotlight-baseline");
const afterDir = path.join(root, "tmp", "spotlight-after");
const diffDir = path.join(root, "tmp", "spotlight-diff");

const WIDTHS = [1280, 1024, 901, 900, 768, 640, 560, 520, 500, 420, 400];
const SLIDE_TYPES = [
  { key: "landscape", indexKey: "landscapeIndex" },
  { key: "portrait", indexKey: "portraitIndex" },
];

const THRESHOLD = 0.08;
const MAX_DIFF_PIXELS = 48;

function parseMode(argv) {
  const arg = argv.find((a) => a.startsWith("--mode="));
  if (arg) return arg.split("=")[1];
  if (argv.includes("--baseline")) return "baseline";
  return "after";
}

async function waitForStableMega(page) {
  await page.waitForSelector("#dashboardMega", { state: "visible", timeout: 15000 });
  await page.waitForFunction(() => window.__demoTest && typeof window.__demoTest.showSlide === "function");
  await page.waitForFunction(() => typeof Chart !== "undefined");
  await page.waitForTimeout(400);
}

async function captureSet(page, outDir) {
  fs.mkdirSync(outDir, { recursive: true });
  for (const width of WIDTHS) {
    await page.setViewportSize({ width, height: 900 });
    await page.waitForTimeout(120);
    for (const slide of SLIDE_TYPES) {
      await page.evaluate((indexKey) => {
        const t = window.__demoTest;
        t.showSlide(t[indexKey]);
      }, slide.indexKey);
      await page.waitForTimeout(200);
      const name = `${width}-${slide.key}.png`;
      const mega = page.locator("#dashboardMega");
      await mega.scrollIntoViewIfNeeded();
      await mega.screenshot({ path: path.join(outDir, name) });
    }
  }
}

function diffPair(baselinePath, afterPath, diffPath) {
  const img1 = PNG.sync.read(fs.readFileSync(baselinePath));
  const img2 = PNG.sync.read(fs.readFileSync(afterPath));
  if (img1.width !== img2.width || img1.height !== img2.height) {
    return { ok: false, reason: `size mismatch ${img1.width}x${img1.height} vs ${img2.width}x${img2.height}` };
  }
  const diff = new PNG({ width: img1.width, height: img1.height });
  const numDiff = pixelmatch(img1.data, img2.data, diff.data, img1.width, img1.height, {
    threshold: THRESHOLD,
    includeAA: true,
  });
  if (numDiff > MAX_DIFF_PIXELS) {
    fs.mkdirSync(path.dirname(diffPath), { recursive: true });
    fs.writeFileSync(diffPath, PNG.sync.write(diff));
    return { ok: false, reason: `${numDiff} pixels differ (max ${MAX_DIFF_PIXELS})` };
  }
  return { ok: true, numDiff };
}

async function main() {
  const mode = parseMode(process.argv.slice(2));
  const outDir = mode === "baseline" ? baselineDir : afterDir;

  const browser = await chromium.launch();
  const context = await browser.newContext({
    reducedMotion: "reduce",
    deviceScaleFactor: 1,
  });
  const page = await context.newPage();
  await page.goto(`file:///${landingHtml.replace(/\\/g, "/")}`);
  await waitForStableMega(page);
  await captureSet(page, outDir);
  await browser.close();

  if (mode === "baseline") {
    console.log(`Baseline captured: ${outDir} (${WIDTHS.length * SLIDE_TYPES.length} PNGs)`);
    return;
  }

  if (!fs.existsSync(baselineDir)) {
    console.error("Missing baseline. Run: npm run check:spotlight:baseline");
    process.exit(1);
  }

  let failed = 0;
  for (const width of WIDTHS) {
    for (const slide of SLIDE_TYPES) {
      const name = `${width}-${slide.key}.png`;
      const base = path.join(baselineDir, name);
      const after = path.join(afterDir, name);
      const diff = path.join(diffDir, name);
      if (!fs.existsSync(base)) {
        console.error(`FAIL ${name}: missing baseline`);
        failed++;
        continue;
      }
      if (!fs.existsSync(after)) {
        console.error(`FAIL ${name}: missing after capture`);
        failed++;
        continue;
      }
      const result = diffPair(base, after, diff);
      if (result.ok) {
        console.log(`OK   ${name} (${result.numDiff} px)`);
      } else {
        console.error(`FAIL ${name}: ${result.reason}`);
        failed++;
      }
    }
  }

  if (failed) {
    console.error(`\n${failed} screenshot(s) failed pixel diff. See ${diffDir}`);
    process.exit(1);
  }
  console.log("\nAll spotlight visual checks passed.");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
