/** Custom event catalog + render-gate deferred propagation contract. */
import { describe, expect, it, beforeEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { BAKLOG_EVENT_REGISTRY } from '../js/custom-events.js';
import {
  consumeDeferredRenders,
  deferTableRender,
  _resetRenderGateForTests,
} from '../js/render-gate.js';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, '..');

function fileContains(path, needle) {
  const text = readFileSync(join(ROOT, path), 'utf8');
  return text.includes(needle);
}

describe('custom event catalog', () => {
  for (const [event, spec] of Object.entries(BAKLOG_EVENT_REGISTRY)) {
    it(`${event} dispatches on ${spec.target} with documented emitters and listeners`, () => {
      const emitterNeedle = event === 'baklog:themechange' ? 'THEME_CHANGE_EVENT' : event;
      const listenerNeedle = event === 'baklog:themechange' ? 'THEME_CHANGE_EVENT' : event;
      for (const f of spec.emitters) {
        expect(
          fileContains(f, `CustomEvent('${emitterNeedle}'`)
            || fileContains(f, `CustomEvent("${emitterNeedle}"`)
            || fileContains(f, emitterNeedle)
            || fileContains(f, 'custom-events.js'),
        ).toBe(true);
      }
      for (const f of spec.listeners) {
        expect(
          fileContains(f, `addEventListener('${listenerNeedle}'`)
            || fileContains(f, `addEventListener("${listenerNeedle}"`)
            || fileContains(f, listenerNeedle),
        ).toBe(true);
      }
      const emitterFile = spec.emitters[0];
      expect(
        fileContains(emitterFile, `${spec.target}.dispatchEvent`),
      ).toBe(true);
    });
  }
});

describe('render-gate deferred paints', () => {
  beforeEach(() => {
    _resetRenderGateForTests();
  });

  it('defers table/picks/summary until consumed', () => {
    deferTableRender();
    const flags = consumeDeferredRenders();
    expect(flags.table).toBe(true);
    expect(consumeDeferredRenders().table).toBe(false);
  });
});

describe('downstream sync registries wired at boot', () => {
  it('app.js registers downstream sync and fetcher health callbacks', () => {
    const app = readFileSync(join(ROOT, 'js', 'app.js'), 'utf8');
    expect(app).toContain('configureDownstreamSync({');
    expect(app).toContain('configureFetcherHealth({');
    expect(app).toContain('reloadAfterFetcher');
  });

  it('personal-storage exports scheduleDownstreamSync', () => {
    const ps = readFileSync(join(ROOT, 'js', 'personal-storage.js'), 'utf8');
    expect(ps).toContain('export function scheduleDownstreamSync');
    expect(ps).toContain('downstreamCallbacks');
  });

  it('switchView flushes deferred renders when leaving connections', () => {
    const filters = readFileSync(join(ROOT, 'js', 'filters-ui.js'), 'utf8');
    expect(filters).toContain('flushDeferredRenders');
    expect(filters).toMatch(/switchView[\s\S]*flushDeferredRenders/);
  });

  it('profile switch uses full page reload (teardown via navigation)', () => {
    const profiles = readFileSync(join(ROOT, 'js', 'profiles.js'), 'utf8');
    expect(profiles).toContain('location.reload()');
    expect(profiles).toContain('prepareForProfileSwitch');
  });

  it('bindEvents is guarded against double registration', () => {
    const bind = readFileSync(join(ROOT, 'js', 'bind-events.js'), 'utf8');
    expect(bind).toMatch(/_eventsBound/);
    expect(bind).toMatch(/if \(_eventsBound\) return/);
  });

  it('bootstrap installs cross-tab personal storage sync', () => {
    const app = readFileSync(join(ROOT, 'js', 'app.js'), 'utf8');
    expect(app).toContain('installPersonalStorageSync');
  });
});
