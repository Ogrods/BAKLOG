import { describe, expect, it, beforeEach } from 'vitest';
import {
  metricsPrefsKey,
  loadDisabledMetrics,
  toggleMetric,
  resetAllMetricsUsed,
  saveDisabledMetrics,
  computeUnusedFromRendered,
  seedUnusedFromRendered,
  loadRenderedMetrics,
  hasSeededUnused,
  renderedMetricsKey,
  seedUntappedBatchToUnused,
  hasSeededUntappedBatch,
} from '../admin/metrics-prefs.js';
import { UNTAPPED_BATCH_METRIC_KEYS } from '../js/metrics-untapped-batch.js';

function mockStorage() {
  /** @type {Record<string, string>} */
  const data = {};
  return {
    getItem(key) {
      return Object.prototype.hasOwnProperty.call(data, key) ? data[key] : null;
    },
    setItem(key, value) {
      data[key] = String(value);
    },
    removeItem(key) {
      delete data[key];
    },
    _data: data,
  };
}

describe('admin metrics-prefs', () => {
  /** @type {ReturnType<typeof mockStorage>} */
  let storage;

  beforeEach(() => {
    storage = mockStorage();
  });

  it('uses profile-scoped prefs keys', () => {
    expect(metricsPrefsKey('default')).toBe('steam-backlog-ui-prefs');
    expect(metricsPrefsKey('work')).toBe('steam-backlog-ui-prefs:work');
  });

  it('round-trips disabled metrics without clobbering other prefs', () => {
    storage.setItem('steam-backlog-ui-prefs', JSON.stringify({
      quickWinMaxHours: 12,
      columns: { library: { score: false } },
    }));
    saveDisabledMetrics(['games owned', 'backlog OPS'], storage, 'default');
    const raw = JSON.parse(storage.getItem('steam-backlog-ui-prefs'));
    expect(raw.quickWinMaxHours).toBe(12);
    expect(raw.columns.library.score).toBe(false);
    expect(raw.metricsDisabled).toEqual(['games owned', 'backlog OPS']);
    expect(loadDisabledMetrics(storage, 'default')).toEqual(['games owned', 'backlog OPS']);
  });

  it('toggleMetric adds and removes keys', () => {
    let disabled = [];
    disabled = toggleMetric('stores', disabled, storage, 'default');
    expect(disabled).toEqual(['stores']);
    disabled = toggleMetric('stores', disabled, storage, 'default');
    expect(disabled).toEqual([]);
  });

  it('resetAllMetricsUsed clears disabled list', () => {
    saveDisabledMetrics(['completed'], storage, 'default');
    expect(resetAllMetricsUsed(storage, 'default')).toEqual([]);
    expect(loadDisabledMetrics(storage, 'default')).toEqual([]);
  });

  describe('rendered split', () => {
    const catalog = ['games owned', 'stores', 'gamerscore earned', 'first PSN session'];

    it('computeUnusedFromRendered returns catalog minus rendered', () => {
      const disabled = computeUnusedFromRendered(catalog, ['games owned', 'stores']);
      expect(disabled).toEqual(['gamerscore earned', 'first PSN session']);
    });

    it('computeUnusedFromRendered preserves manual hides of data-having metrics', () => {
      // 'stores' has data (rendered) but was manually hidden — it must stay Unused.
      const disabled = computeUnusedFromRendered(
        catalog,
        ['games owned', 'stores'],
        ['stores'],
      );
      expect(disabled).toEqual(['stores', 'gamerscore earned', 'first PSN session']);
    });

    it('computeUnusedFromRendered drops stale manual hides for metrics that lost data', () => {
      // 'gamerscore earned' was manually hidden but is no longer rendered; it falls
      // into the no-data bucket rather than being duplicated.
      const disabled = computeUnusedFromRendered(
        catalog,
        ['games owned', 'stores'],
        ['gamerscore earned'],
      );
      expect(disabled).toEqual(['gamerscore earned', 'first PSN session']);
    });

    it('seedUnusedFromRendered keeps a manual hide of a data-having metric', () => {
      storage.setItem(renderedMetricsKey('default'), JSON.stringify(['games owned', 'stores']));
      saveDisabledMetrics(['stores'], storage, 'default');
      const disabled = seedUnusedFromRendered(catalog, storage, 'default');
      expect(disabled).toEqual(['stores', 'gamerscore earned', 'first PSN session']);
    });

    it('loadRenderedMetrics reads the profile-scoped rendered key', () => {
      storage.setItem(renderedMetricsKey('default'), JSON.stringify(['games owned']));
      expect(loadRenderedMetrics(storage, 'default')).toEqual(['games owned']);
      expect(renderedMetricsKey('work')).toBe('baklog-metrics-rendered:work');
    });

    it('seedUnusedFromRendered disables non-rendered metrics and sets the seeded marker', () => {
      storage.setItem(renderedMetricsKey('default'), JSON.stringify(['games owned', 'stores']));
      expect(hasSeededUnused(storage, 'default')).toBe(false);
      const disabled = seedUnusedFromRendered(catalog, storage, 'default');
      expect(disabled).toEqual(['gamerscore earned', 'first PSN session']);
      expect(loadDisabledMetrics(storage, 'default')).toEqual(['gamerscore earned', 'first PSN session']);
      expect(hasSeededUnused(storage, 'default')).toBe(true);
    });
  });

  describe('untapped batch seed', () => {
    it('seedUntappedBatchToUnused adds batch keys once', () => {
      expect(hasSeededUntappedBatch(storage, 'default')).toBe(false);
      const disabled = seedUntappedBatchToUnused(storage, 'default');
      expect(hasSeededUntappedBatch(storage, 'default')).toBe(true);
      for (const key of UNTAPPED_BATCH_METRIC_KEYS) {
        expect(disabled).toContain(key);
      }
      const again = seedUntappedBatchToUnused(storage, 'default');
      expect(again.length).toBe(disabled.length);
    });

    it('batch seed preserves existing manual disables', () => {
      saveDisabledMetrics(['games owned'], storage, 'default');
      const disabled = seedUntappedBatchToUnused(storage, 'default');
      expect(disabled).toContain('games owned');
      expect(disabled).toContain('Deck-ready %');
    });
  });
});
