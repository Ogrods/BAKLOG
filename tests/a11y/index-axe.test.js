/** axe-core accessibility scan of index.html (Lighthouse-aligned CI gate). */
import fs from 'node:fs';
import path from 'node:path';
import { beforeEach, describe, expect, it } from 'vitest';
import axe from 'axe-core';
import { hydrateIndexDocument } from './hydrate-index.js';

const KNOWN_PATH = path.join(import.meta.dirname, 'known-violations.json');
const FAIL_IMPACT = new Set(['serious', 'critical']);

function loadAllowlist() {
  try {
    const raw = fs.readFileSync(KNOWN_PATH, 'utf8');
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function violationKey(v) {
  return `${v.id}::${v.impact}`;
}

function isAllowed(v, allowlist) {
  return allowlist.some(
    (entry) => entry.id === v.id && (!entry.impact || entry.impact === v.impact),
  );
}

function runAxe() {
  return new Promise((resolve, reject) => {
    axe.run(document, { resultTypes: ['violations'] }, (err, results) => {
      if (err) reject(err);
      else resolve(results);
    });
  });
}

describe('index.html axe accessibility', () => {
  beforeEach(() => {
    hydrateIndexDocument();
  });

  it('has no serious or critical violations outside the allowlist', async () => {
    const results = await runAxe();
    const allowlist = loadAllowlist();

    const failing = [];
    const moderate = [];

    for (const v of results.violations) {
      if (isAllowed(v, allowlist)) continue;
      if (FAIL_IMPACT.has(v.impact)) {
        failing.push(v);
      } else {
        moderate.push(v);
      }
    }

    if (moderate.length) {
      const summary = moderate.map((v) => `  [${v.impact}] ${v.id} (${v.nodes.length} nodes)`).join('\n');
      console.warn(`axe moderate/minor violations (non-blocking):\n${summary}`);
    }

    if (failing.length) {
      const detail = failing
        .map((v) => {
          const targets = v.nodes.slice(0, 3).map((n) => n.target.join(' > ')).join('; ');
          return `[${v.impact}] ${v.id}: ${v.help}\n  nodes: ${targets}`;
        })
        .join('\n\n');
      expect.fail(`axe serious/critical violations:\n\n${detail}`);
    }
  });
});
