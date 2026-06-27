/** axe-core accessibility scan of landing/index.html. */
import fs from 'node:fs';
import path from 'node:path';
import { beforeEach, describe, expect, it } from 'vitest';
import axe from 'axe-core';
import { hydrateLandingDocument } from './hydrate-landing.js';

const KNOWN_PATH = path.join(import.meta.dirname, 'landing-known-violations.json');
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

function runAxe() {
  return new Promise((resolve, reject) => {
    axe.run(document, { resultTypes: ['violations'] }, (err, results) => {
      if (err) reject(err);
      else resolve(results);
    });
  });
}

describe('landing/index.html axe accessibility', () => {
  beforeEach(() => {
    hydrateLandingDocument();
  });

  it('has no serious or critical violations outside the allowlist', async () => {
    const results = await runAxe();
    const allowlist = loadAllowlist();
    const failing = (results.violations || []).filter(
      (v) => FAIL_IMPACT.has(v.impact) && !allowlist.some((e) => e.id === v.id),
    );
    if (failing.length) {
      const detail = failing.map((v) => `${v.id} (${v.impact}): ${v.help}`).join('\n');
      expect.fail(`axe serious/critical violations:\n\n${detail}`);
    }
  });
});
