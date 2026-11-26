/**
 * Generate committed spotlight edge-marker PNG fixtures.
 * Run once: node scripts/gen-spotlight-fixtures.mjs
 */
import fs from "node:fs";
import path from "node:path";
import { PNG } from "pngjs";

const outDir = path.resolve(import.meta.dirname, "..", "tests", "fixtures", "spotlight");

function fillRect(png, x0, y0, w, h, [r, g, b, a = 255]) {
  const { width, height, data } = png;
  const x1 = Math.min(width, x0 + w);
  const y1 = Math.min(height, y0 + h);
  for (let y = Math.max(0, y0); y < y1; y++) {
    for (let x = Math.max(0, x0); x < x1; x++) {
      const i = (width * y + x) << 2;
      data[i] = r;
      data[i + 1] = g;
      data[i + 2] = b;
      data[i + 3] = a;
    }
  }
}

function writePng(name, width, height, paint) {
  const png = new PNG({ width, height });
  // Dark charcoal base so markers contrast.
  fillRect(png, 0, 0, width, height, [32, 32, 40]);
  paint(png);
  fs.mkdirSync(outDir, { recursive: true });
  const dest = path.join(outDir, name);
  fs.writeFileSync(dest, PNG.sync.write(png));
  console.log(`wrote ${dest} (${width}x${height})`);
}

// Portrait 600x900: thick edge markers survive soft L/R feather (~3.5%).
writePng("portrait-600x900.png", 600, 900, (png) => {
  // Thick bars: soft L/R feather (~3.5%) + probe samples must still land inside.
  fillRect(png, 0, 0, 96, 900, [220, 20, 60]); // red left
  fillRect(png, 504, 0, 96, 900, [30, 90, 220]); // blue right
  fillRect(png, 0, 780, 600, 120, [50, 220, 50]); // lime bottom
  fillRect(png, 110, 40, 380, 56, [250, 250, 250]); // white title band
});

writePng("hero-1920x620.png", 1920, 620, (png) => {
  fillRect(png, 0, 0, 64, 620, [220, 20, 60]);
  fillRect(png, 1856, 0, 64, 620, [30, 90, 220]);
  fillRect(png, 0, 560, 1920, 60, [50, 220, 50]);
  fillRect(png, 200, 80, 1520, 80, [250, 250, 250]);
});

writePng("square-400x400.png", 400, 400, (png) => {
  fillRect(png, 0, 0, 40, 400, [220, 20, 60]);
  fillRect(png, 360, 0, 40, 400, [30, 90, 220]);
  fillRect(png, 0, 360, 400, 40, [50, 220, 50]);
  fillRect(png, 40, 40, 320, 48, [250, 250, 250]);
});

writePng("lowres-460x215.png", 460, 215, (png) => {
  fillRect(png, 0, 0, 32, 215, [220, 20, 60]);
  fillRect(png, 428, 0, 32, 215, [30, 90, 220]);
  fillRect(png, 0, 183, 460, 32, [50, 220, 50]);
  fillRect(png, 40, 30, 380, 40, [250, 250, 250]);
});
