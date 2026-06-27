import { beforeEach, describe, expect, it, vi } from 'vitest';
import { bindFetcherHealthEvents } from '../js/bind-events-fetcher.js';
import { fetcherRunner } from '../js/fetcher-health.js';

describe('Run stale click wiring', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="dashboardFetcherHealth">
        <button type="button" class="fh-run-stale">Run stale (2)</button>
        <button type="button" class="fh-run-stale" disabled>Run stale (0)</button>
      </div>
    `;
    bindFetcherHealthEvents();
  });

  it('calls runAllStale when enabled button is clicked', () => {
    const spy = vi.spyOn(fetcherRunner, 'runAllStale').mockResolvedValue(undefined);
    document.querySelector('.fh-run-stale:not([disabled])').click();
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it('does not call runAllStale when disabled button is clicked', () => {
    const spy = vi.spyOn(fetcherRunner, 'runAllStale').mockResolvedValue(undefined);
    document.querySelector('.fh-run-stale[disabled]').click();
    expect(spy).not.toHaveBeenCalled();
  });
});
