import { describe, it, expect, beforeAll, beforeEach, afterAll } from 'vitest';
import { initTrophyPopover } from '../js/trophy-popover.js';

function makePill(attrs = {}) {
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'trophy-pill';
  btn.dataset.trophyPop = '';
  btn.dataset.store = attrs.store ?? 'xbox';
  btn.dataset.pct = String(attrs.pct ?? 50);
  btn.dataset.label = attrs.label ?? 'Xbox achievement completion';
  if (attrs.gsCur != null) btn.dataset.gsCur = String(attrs.gsCur);
  if (attrs.gsTotal != null) btn.dataset.gsTotal = String(attrs.gsTotal);
  btn.setAttribute('aria-haspopup', 'true');
  btn.setAttribute('aria-expanded', 'false');
  btn.textContent = '🏆 50%';
  document.body.appendChild(btn);
  return btn;
}

describe('trophy popover', () => {
  beforeAll(() => {
    initTrophyPopover();
  });

  beforeEach(() => {
    document.body.innerHTML = '';
    const pop = document.getElementById('trophyPop');
    if (pop) {
      pop.hidden = true;
      pop.innerHTML = '';
    }
  });

  afterAll(() => {
    document.body.innerHTML = '';
    document.getElementById('trophyPop')?.remove();
    delete document.documentElement.dataset.trophyPopInit;
  });

  it('pins open on click with completion and gamerscore', () => {
    const pill = makePill({ gsCur: 300, gsTotal: 1000 });
    pill.click();

    const pop = document.getElementById('trophyPop');
    expect(pop).toBeTruthy();
    expect(pop.hidden).toBe(false);
    expect(pop.querySelector('.trophy-pop-pct')?.textContent).toBe('50%');
    expect(pop.querySelector('.trophy-pop-gs')?.textContent).toMatch(/300/);
    expect(pop.querySelector('.trophy-pop-gs')?.textContent).toMatch(/1,000/);
    expect(pill.getAttribute('aria-expanded')).toBe('true');
  });

  it('dismisses pinned popover on Escape', () => {
    const pill = makePill();
    pill.click();
    const pop = document.getElementById('trophyPop');
    expect(pop.hidden).toBe(false);

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(pop.hidden).toBe(true);
    expect(pill.getAttribute('aria-expanded')).toBe('false');
  });

  it('toggles off when clicking the same pill again', () => {
    const pill = makePill();
    pill.click();
    const pop = document.getElementById('trophyPop');
    expect(pop.hidden).toBe(false);

    pill.click();
    expect(pop.hidden).toBe(true);
    expect(pill.getAttribute('aria-expanded')).toBe('false');
  });
});
