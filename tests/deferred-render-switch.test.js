/** Phase 3: deferred renders survive dashboard hops; paint on table views. */
import { beforeEach, describe, expect, it, vi } from 'vitest';

describe('flushDeferredRenders view gating', () => {
  beforeEach(() => {
    vi.resetModules();
  });

  it('does not consume deferred flags when active view is not a table view', async () => {
    const {
      deferTableRender,
      deferSummaryRender,
      consumeDeferredRenders,
      _resetRenderGateForTests,
    } = await import('../js/render-gate.js');
    _resetRenderGateForTests();
    deferTableRender();
    deferSummaryRender();
    const { state } = await import('../js/state.js');
    state.activeView = 'dashboard';
    const { flushDeferredRenders } = await import('../js/filters-ui.js');
    await flushDeferredRenders();
    const flags = consumeDeferredRenders();
    expect(flags.table).toBe(true);
    expect(flags.summary).toBe(true);
  });

  it('checks isTableDataView before consuming deferred flags', async () => {
    const { readFileSync } = await import('node:fs');
    const { fileURLToPath } = await import('node:url');
    const { dirname, join } = await import('node:path');
    const root = join(dirname(fileURLToPath(import.meta.url)), '..');
    const filters = readFileSync(join(root, 'js', 'filters-ui.js'), 'utf8');
    expect(filters).toMatch(
      /if \(!isTableDataView\(state\.activeView\)\) return;\s*\n\s*const flags = consumeDeferredRenders\(\)/,
    );
  });
});
