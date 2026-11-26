/**
 * Playwright pixel probe: tall portrait spotlight must not center-crop edge markers.
 *
 *   node tests/spotlight-uncropped.spec.js
 *   npm run test:spotlight-uncropped
 */
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import { PNG } from "pngjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const FIXTURE = path.join(root, "tests", "fixtures", "spotlight");

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".png": "image/png",
  ".js": "text/javascript; charset=utf-8",
};

function startStaticServer() {
  const server = http.createServer((req, res) => {
    const urlPath = decodeURIComponent((req.url || "/").split("?")[0]);
    const rel = urlPath === "/" ? "/tests/fixtures/spotlight/harness.html" : urlPath;
    const filePath = path.normalize(path.join(root, rel.replace(/^\//, "")));
    if (!filePath.startsWith(root) || !fs.existsSync(filePath) || fs.statSync(filePath).isDirectory()) {
      res.writeHead(404);
      res.end("not found");
      return;
    }
    const ext = path.extname(filePath).toLowerCase();
    res.writeHead(200, { "Content-Type": MIME[ext] || "application/octet-stream" });
    fs.createReadStream(filePath).pipe(res);
  });
  return new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address();
      resolve({ server, base: `http://127.0.0.1:${port}` });
    });
  });
}

function sample(png, x, y) {
  const xi = Math.max(0, Math.min(png.width - 1, Math.round(x)));
  const yi = Math.max(0, Math.min(png.height - 1, Math.round(y)));
  const i = (png.width * yi + xi) << 2;
  return {
    r: png.data[i],
    g: png.data[i + 1],
    b: png.data[i + 2],
    a: png.data[i + 3],
  };
}

function isRed(c) {
  return c.r > 150 && c.g < 110 && c.b < 110;
}
function isBlue(c) {
  return c.b > 150 && c.r < 110 && c.g < 140;
}
function isLime(c) {
  return c.g > 150 && c.r < 140 && c.b < 140;
}

async function main() {
  const { server, base } = await startStaticServer();
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
    await page.goto(`${base}/tests/fixtures/spotlight/harness.html`, {
      waitUntil: "networkidle",
    });
    await page.waitForFunction(() => window.__harnessReady === true, null, {
      timeout: 10000,
    });
    // Wait one paint after fit stamps.
    await page.waitForTimeout(120);

    const box = await page.locator("#art").boundingBox();
    if (!box || box.width < 80 || box.height < 120) {
      throw new Error(`art box too small or missing: ${JSON.stringify(box)}`);
    }

    // Intrinsic card: height ~380 in a 400 slot; width follows 2:3 ≈ 253.
    // Full-bleed crop failure would stretch img to ~1200x400 and lose edge bars.
    if (box.width > 500) {
      throw new Error(
        `portrait art box too wide (${box.width.toFixed(1)}px) - likely full-bleed crop layout`,
      );
    }

    const shotPath = path.join(FIXTURE, "_probe-portrait.png");
    await page.locator("#slot").screenshot({ path: shotPath });
    const png = PNG.sync.read(fs.readFileSync(shotPath));

    // Element screenshot coords are relative to #slot, not the viewport.
    const slotBox = await page.locator("#slot").boundingBox();
    const ax = box.x - slotBox.x;
    const ay = box.y - slotBox.y;
    // Past soft L/R feather (~3.5%); thick edge markers cover ~16% of width/height.
    const left = sample(png, ax + box.width * 0.06, ay + box.height * 0.5);
    const right = sample(png, ax + box.width * 0.94, ay + box.height * 0.5);
    const bottom = sample(png, ax + box.width * 0.5, ay + box.height * 0.97);

    const failures = [];
    if (!isRed(left)) failures.push(`left marker not red: ${JSON.stringify(left)}`);
    if (!isBlue(right)) failures.push(`right marker not blue: ${JSON.stringify(right)}`);
    if (!isLime(bottom)) failures.push(`bottom marker not lime: ${JSON.stringify(bottom)}`);

    if (failures.length) {
      console.error("FAIL spotlight uncropped probe");
      for (const f of failures) console.error(" -", f);
      console.error(`art box: ${JSON.stringify(box)}`);
      console.error(`screenshot: ${shotPath}`);
      process.exitCode = 1;
      return;
    }

    console.log(
      `OK portrait uncropped (box ${box.width.toFixed(0)}x${box.height.toFixed(0)}; markers red/blue/lime present)`,
    );

    // Square path still uncropped (optional secondary).
    await page.evaluate(() => {
      const spot = document.getElementById("spot");
      const art = document.getElementById("art");
      const bg = document.getElementById("artBg");
      spot.classList.add("has-square-art");
      art.src = "/tests/fixtures/spotlight/square-400x400.png";
      bg.src = art.src;
    });
    await page.waitForFunction(() => {
      const art = document.getElementById("art");
      return art.complete && art.naturalWidth === 400;
    });
    await page.waitForTimeout(80);
    const sqBox = await page.locator("#art").boundingBox();
    const sqShot = path.join(FIXTURE, "_probe-square.png");
    await page.locator("#slot").screenshot({ path: sqShot });
    const sqPng = PNG.sync.read(fs.readFileSync(sqShot));
    const sqAx = sqBox.x - slotBox.x;
    const sqAy = sqBox.y - slotBox.y;
    const sqLeft = sample(sqPng, sqAx + sqBox.width * 0.06, sqAy + sqBox.height * 0.5);
    const sqRight = sample(sqPng, sqAx + sqBox.width * 0.94, sqAy + sqBox.height * 0.5);
    if (!isRed(sqLeft) || !isBlue(sqRight)) {
      console.error("FAIL square uncropped probe", { sqLeft, sqRight, sqBox });
      process.exitCode = 1;
      return;
    }
    console.log(
      `OK square uncropped (box ${sqBox.width.toFixed(0)}x${sqBox.height.toFixed(0)})`,
    );
    for (const name of ["_probe-portrait.png", "_probe-square.png"]) {
      try { fs.unlinkSync(path.join(FIXTURE, name)); } catch { /* keep on fail */ }
    }
  } finally {
    await browser.close();
    server.close();
  }
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
