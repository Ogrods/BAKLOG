import { defineConfig } from 'vitest/config';

// Default to happy-dom (lighter than jsdom) so tests can import modules that
// touch `window` / `localStorage` at module scope (e.g. personal-store.js).
// Override per-file with: /* @vitest-environment node */
export default defineConfig({
  test: {
    environment: 'happy-dom',
    include: ['tests/**/*.test.js'],
    globals: false,
  },
});
