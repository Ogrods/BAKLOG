/**
 * Modal geometry measure helpers (Vitest).
 */
import { afterEach, describe, expect, it } from 'vitest';
import { measureModalLayout, MODAL_GEOM_GAP_PX } from '../js/modal-geom-api.js';

function mountModal(html) {
  document.body.insertAdjacentHTML('beforeend', html);
}

describe('measureModalLayout', () => {
  afterEach(() => {
    document.getElementById('testModal')?.remove();
  });

  it('passes when body and actions have required gap', () => {
    mountModal(`
      <div id="testModal" class="app-modal">
        <div role="dialog" class="flex flex-col" style="display:flex;flex-direction:column;gap:4px">
          <div class="app-modal-body" style="height:40px">body</div>
          <div class="app-modal-actions" style="height:32px">actions</div>
        </div>
      </div>
    `);
    const panel = document.querySelector('#testModal [role="dialog"]');
    const body = panel.querySelector('.app-modal-body');
    const actions = panel.querySelector('.app-modal-actions');
    body.getBoundingClientRect = () => ({
      top: 0, bottom: 40, left: 0, right: 100, width: 100, height: 40, x: 0, y: 0, toJSON() {},
    });
    actions.getBoundingClientRect = () => ({
      top: 44, bottom: 76, left: 0, right: 100, width: 100, height: 32, x: 0, y: 44, toJSON() {},
    });
    panel.getBoundingClientRect = () => ({
      top: 0, bottom: 80, left: 0, right: 100, width: 100, height: 80, x: 0, y: 0, toJSON() {},
    });

    const result = measureModalLayout('testModal');
    expect(result.ok).toBe(true);
    expect(result.gap).toBeGreaterThanOrEqual(MODAL_GEOM_GAP_PX);
  });

  it('fails when body overlaps actions', () => {
    mountModal(`
      <div id="testModal" class="app-modal">
        <div role="dialog">
          <div class="app-modal-body">body</div>
          <div class="app-modal-actions">actions</div>
        </div>
      </div>
    `);
    const panel = document.querySelector('#testModal [role="dialog"]');
    const body = panel.querySelector('.app-modal-body');
    const actions = panel.querySelector('.app-modal-actions');
    body.getBoundingClientRect = () => ({
      top: 0, bottom: 50, left: 0, right: 100, width: 100, height: 50, x: 0, y: 0, toJSON() {},
    });
    actions.getBoundingClientRect = () => ({
      top: 48, bottom: 80, left: 0, right: 100, width: 100, height: 32, x: 0, y: 48, toJSON() {},
    });
    panel.getBoundingClientRect = () => ({
      top: 0, bottom: 80, left: 0, right: 100, width: 100, height: 80, x: 0, y: 0, toJSON() {},
    });

    const result = measureModalLayout('testModal');
    expect(result.ok).toBe(false);
    expect(result.reason).toMatch(/overlap/);
  });
});
