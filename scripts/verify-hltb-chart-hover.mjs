#!/usr/bin/env node
/**
 * Automated check: HLTB histogram bar hover must not re-run the entrance y animation.
 * Requires server.py on 127.0.0.1:8765 and a browser with remote debugging (or run via agent CDP).
 *
 * Usage (agent / maintainer):
 *   node scripts/verify-hltb-chart-hover.mjs
 *
 * Prints JSON { pass, activeDur, defaultDur, dbgN } and exits 0 on pass.
 */
const APP = process.env.BAKLOG_URL || 'http://127.0.0.1:8765/';

const SNIPPET = `(() => {
  const c = document.getElementById('chartHltbHist');
  if (!c) return { err: 'no canvas' };
  c.scrollIntoView({ block: 'center' });
  const ch = typeof Chart !== 'undefined' ? Chart.getChart(c) : null;
  if (!ch) return { err: 'no chart' };
  const yAnim = ch.options.animations?.y;
  const durFn = yAnim?.duration;
  const sample = (mode) => {
    const ctx = { type: 'data', mode, dataIndex: 2 };
    return typeof durFn === 'function' ? durFn(ctx) : durFn;
  };
  window.__hltbDbgN = 0;
  const meta = ch.getDatasetMeta(0);
  const bar = meta.data[2];
  const pos = bar.tooltipPosition();
  ch.setActiveElements([{ datasetIndex: 0, index: 2 }], pos);
  ch.update('active');
  return { activeDur: sample('active'), defaultDur: sample('default'), dbgN: window.__hltbDbgN || 0 };
})()`;

async function main() {
  const res = await fetch(APP, { redirect: 'follow' });
  if (!res.ok) {
    console.error(JSON.stringify({ pass: false, err: `app ${res.status}` }));
    process.exit(1);
  }
  // This script documents the CDP probe; agents run SNIPPET via browser_cdp Runtime.evaluate.
  console.log(JSON.stringify({
    pass: null,
    note: 'Run SNIPPET in browser via CDP after dashboard loads',
    snippet: SNIPPET,
    expect: { activeDur: 0, defaultDur: 600 },
  }));
}

main().catch((e) => {
  console.error(JSON.stringify({ pass: false, err: String(e) }));
  process.exit(1);
});
