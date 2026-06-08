import { existsSync } from 'node:fs';
import { defineConfig } from 'vitest/config';

// Default to happy-dom (lighter than jsdom) so tests can import modules that
// touch `window` / `localStorage` at module scope (e.g. personal-store.js).
// Override per-file with: /* @vitest-environment node */
const adminPresent = existsSync('admin/run-console.js');
const adminOnlyTests = [
  'tests/admin-claims-workspace.test.js',
  'tests/admin-pacific-dates.test.js',
  'tests/admin-run-console-lifecycle.test.js',
  'tests/admin-run-console.test.js',
];

export default defineConfig({
  test: {
    environment: 'happy-dom',
    include: ['tests/**/*.test.js'],
    // admin/ is gitignored (baklog-internal); skip its unit tests on public CI.
    exclude: adminPresent ? [] : adminOnlyTests,
    globals: false,
  },
});
