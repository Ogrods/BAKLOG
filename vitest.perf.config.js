import { defineConfig } from "vitest/config";
import baseConfig, { perfBudgetTests } from "./vitest.config.js";

// Spread instead of mergeConfig: mergeConfig concatenates arrays, which would
// keep the base exclude list (and with it every perf file).
export default defineConfig({
  ...baseConfig,
  test: {
    ...baseConfig.test,
    include: perfBudgetTests,
    exclude: [],
  },
});
