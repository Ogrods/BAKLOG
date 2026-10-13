/* @vitest-environment node */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import baseConfig, { perfBudgetTests } from '../vitest.config.js';
import perfConfig from '../vitest.perf.config.js';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

describe('perf budget tests run only via npm run test:perf', () => {
  it('every test that reads perf-budget.json is in perfBudgetTests', () => {
    const budgetReaders = fs
      .readdirSync(path.join(root, 'tests'))
      .filter((f) => f.endsWith('.test.js') && f !== path.basename(fileURLToPath(import.meta.url)))
      .filter((f) => fs.readFileSync(path.join(root, 'tests', f), 'utf8').includes('perf-budget.json'))
      .map((f) => `tests/${f}`);
    expect(budgetReaders.length).toBeGreaterThan(0);
    for (const file of budgetReaders) expect(perfBudgetTests).toContain(file);
    for (const file of perfBudgetTests) expect(fs.existsSync(path.join(root, file))).toBe(true);
  });

  it('npm test excludes them and the perf config runs exactly them', () => {
    for (const file of perfBudgetTests) expect(baseConfig.test.exclude).toContain(file);
    expect(perfConfig.test.include).toEqual(perfBudgetTests);
    expect(perfConfig.test.exclude).toEqual([]);
  });

  it('test:perf uses the perf config', () => {
    const pkg = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8'));
    expect(pkg.scripts['test:perf']).toBe('vitest run --config vitest.perf.config.js');
  });
});
