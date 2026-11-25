import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  parseStallLogLine,
  updateStallNotice,
  wireStallRetryOnce,
} from '../js/fetcher/runner/stall-notice.js';

describe('parseStallLogLine', () => {
  it('parses still-running stall notices', () => {
    expect(
      parseStallLogLine('[server] no output for 60s — still running (PID 123)'),
    ).toEqual({ seconds: 60, fatal: false, soft: false });
    expect(
      parseStallLogLine('[server] no output for 90s - still running (PID 9)'),
    ).toEqual({ seconds: 90, fatal: false, soft: false });
  });

  it('parses force-kill notices as fatal', () => {
    expect(
      parseStallLogLine('[server] no output for 180s — force-killing PID 44'),
    ).toEqual({ seconds: 180, fatal: true, soft: false });
  });

  it('returns null for unrelated lines', () => {
    expect(parseStallLogLine('[server] cancelled 1 run(s)')).toBeNull();
    expect(parseStallLogLine('')).toBeNull();
  });
});

describe('updateStallNotice + wireStallRetryOnce', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="fhLog" class="fh-log">
        <div class="fh-log-head"><span data-role="title">log</span></div>
        <div class="fh-log-body" data-role="body"></div>
      </div>
    `;
  });

  it('renders CTA and invokes force-reset on click', async () => {
    const panel = document.getElementById('fhLog');
    const onRetry = vi.fn();
    wireStallRetryOnce(panel, onRetry);
    updateStallNotice(panel, { seconds: 60, fatal: false });
    const notice = panel.querySelector('[data-role="stall-notice"]');
    expect(notice?.textContent).toContain('No output for 60s');
    notice.querySelector('[data-role="stall-retry"]').click();
    expect(onRetry).toHaveBeenCalledTimes(1);
    updateStallNotice(panel, null);
    expect(notice.classList.contains('hidden')).toBe(true);
  });

  it('soft stall shows copy without force-reset CTA', () => {
    const panel = document.getElementById('fhLog');
    updateStallNotice(panel, { seconds: 30, fatal: false, soft: true });
    const notice = panel.querySelector('[data-role="stall-notice"]');
    expect(notice?.textContent).toContain('No progress update for 30s');
    expect(notice?.querySelector('[data-role="stall-retry"]')).toBeNull();
  });
});
