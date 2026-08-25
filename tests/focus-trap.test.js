import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { isFocusableVisible } from '../js/focus-trap.js';

describe('isFocusableVisible', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('includes position:fixed controls (offsetParent is null)', () => {
    const btn = document.createElement('button');
    btn.style.position = 'fixed';
    btn.style.top = '0';
    btn.style.left = '0';
    document.body.appendChild(btn);
    // happy-dom may report undefined; browsers report null for fixed elements.
    expect(btn.offsetParent == null).toBe(true);
    expect(isFocusableVisible(btn)).toBe(true);
  });

  it('excludes display:none and visibility:hidden and disabled', () => {
    const hidden = document.createElement('button');
    hidden.style.display = 'none';
    document.body.appendChild(hidden);
    expect(isFocusableVisible(hidden)).toBe(false);

    const invis = document.createElement('button');
    invis.style.visibility = 'hidden';
    document.body.appendChild(invis);
    expect(isFocusableVisible(invis)).toBe(false);

    const disabled = document.createElement('button');
    disabled.disabled = true;
    document.body.appendChild(disabled);
    expect(isFocusableVisible(disabled)).toBe(false);
  });
});
