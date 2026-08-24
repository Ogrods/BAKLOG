/**
 * Unit smoke for drill geometry measure helpers (jsdom — not a viewport substitute).
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Window } from 'happy-dom';

describe('drill geometry measure API', () => {
  beforeEach(async () => {
    const win = new Window({ url: 'http://127.0.0.1:8765/' });
    global.window = win;
    global.document = win.document;
    global.CSS = { escape: (s) => String(s).replace(/"/g, '\\"') };
    document.body.innerHTML = `
      <div id="toolbarSection" style="height:40px">toolbar</div>
      <div id="tableShell">
        <table class="games-table"><thead></thead>
          <tbody id="tbody">
            <tr data-row-key="steam:1" data-row-index="0"><td>A</td></tr>
          </tbody>
        </table>
      </div>
    `;
    vi.resetModules();
  });

  it('measureDrillRowGeometry reports row-missing for unknown keys', async () => {
    const { measureDrillRowGeometry } = await import('../js/table-ui.js');
    const m = measureDrillRowGeometry('steam:missing');
    expect(m.ok).toBe(false);
    expect(m.reason).toBe('row-missing');
  });

  it('measureDrillRowGeometry returns shape for painted row', async () => {
    const row = document.querySelector('tr[data-row-key="steam:1"]');
    Object.defineProperty(row, 'getBoundingClientRect', {
      configurable: true,
      value: () => ({ top: 200, bottom: 276, height: 76, left: 0, right: 100, width: 100 }),
    });
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 700 });
    Object.defineProperty(window, 'scrollY', { configurable: true, value: 0 });
    const { measureDrillRowGeometry, DRILL_ROW_VERIFY_THRESHOLD_PX } = await import('../js/table-ui.js');
    const m = measureDrillRowGeometry('steam:1');
    expect(m.key).toBe('steam:1');
    expect(typeof m.delta).toBe('number');
    expect(typeof m.aim).toBe('number');
    expect(m.threshold).toBe(DRILL_ROW_VERIFY_THRESHOLD_PX);
  });

  it('measureDrillToolbarGeometry returns toolbar-missing when hidden', async () => {
    document.getElementById('toolbarSection')?.classList.add('hidden');
    const { measureDrillToolbarGeometry } = await import('../js/table-ui.js');
    const m = measureDrillToolbarGeometry();
    expect(m.ok).toBe(false);
    expect(m.reason).toBe('toolbar-missing');
  });
});
