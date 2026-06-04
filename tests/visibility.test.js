import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  isPageHidden,
  registerPausable,
  onVisible,
  _resetVisibilityForTests,
} from '../js/visibility.js';

describe('visibility', () => {
  beforeEach(() => {
    _resetVisibilityForTests();
    Object.defineProperty(document, 'visibilityState', {
      configurable: true,
      value: 'visible',
    });
  });

  afterEach(() => {
    _resetVisibilityForTests();
  });

  it('isPageHidden reflects document.visibilityState', () => {
    expect(isPageHidden()).toBe(false);
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' });
    expect(isPageHidden()).toBe(true);
  });

  it('registerPausable calls pause/resume on visibilitychange', () => {
    const pause = vi.fn();
    const resume = vi.fn();
    registerPausable({ pause, resume });

    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' });
    document.dispatchEvent(new Event('visibilitychange'));
    expect(pause).toHaveBeenCalledTimes(1);

    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
    document.dispatchEvent(new Event('visibilitychange'));
    expect(resume).toHaveBeenCalledTimes(1);
  });

  it('onVisible fires when tab becomes visible', () => {
    const fn = vi.fn();
    onVisible(fn);
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' });
    document.dispatchEvent(new Event('visibilitychange'));
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
    document.dispatchEvent(new Event('visibilitychange'));
    expect(fn).toHaveBeenCalledTimes(1);
  });
});
