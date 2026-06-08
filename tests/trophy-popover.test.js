import { describe, it, expect, beforeAll, beforeEach, afterAll, vi } from 'vitest';

const isProMock = vi.fn(() => false);

vi.mock('../js/auth-gate.js', () => ({
  isPro: () => isProMock(),
}));

import { initTrophyPopover } from '../js/trophy-popover.js';

function makePill(attrs = {}) {
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'trophy-pill';
  btn.dataset.trophyPop = '';
  btn.dataset.store = attrs.store ?? 'xbox';
  btn.dataset.pct = String(attrs.pct ?? 50);
  btn.dataset.label = attrs.label ?? 'Xbox achievement completion';
  if (attrs.key != null) btn.dataset.key = String(attrs.key);
  if (attrs.name != null) btn.dataset.name = String(attrs.name);
  if (attrs.gsCur != null) btn.dataset.gsCur = String(attrs.gsCur);
  if (attrs.gsTotal != null) btn.dataset.gsTotal = String(attrs.gsTotal);
  if (attrs.troCur != null) btn.dataset.troCur = String(attrs.troCur);
  if (attrs.troTotal != null) btn.dataset.troTotal = String(attrs.troTotal);
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
    isProMock.mockReturnValue(false);
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

  function hover(pill) {
    pill.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
  }

  function unhover(pill) {
    pill.dispatchEvent(new MouseEvent('mouseout', { bubbles: true, relatedTarget: document.body }));
  }

  it('opens on hover with completion and gamerscore', () => {
    const pill = makePill({ gsCur: 300, gsTotal: 1000 });
    hover(pill);

    const pop = document.getElementById('trophyPop');
    expect(pop).toBeTruthy();
    expect(pop.hidden).toBe(false);
    expect(pop.querySelector('.trophy-pop-pct')?.textContent).toBe('50%');
    expect(pop.querySelector('.trophy-pop-gs')?.textContent).toMatch(/300/);
    expect(pop.querySelector('.trophy-pop-gs')?.textContent).toMatch(/1,000/);
    expect(pill.getAttribute('aria-expanded')).toBe('true');
  });

  it('opens on hover with PSN trophy counts', () => {
    const pill = makePill({ store: 'psn', label: 'PSN trophy completion', troCur: 12, troTotal: 33 });
    hover(pill);

    const pop = document.getElementById('trophyPop');
    expect(pop).toBeTruthy();
    expect(pop.hidden).toBe(false);
    expect(pop.querySelector('.trophy-pop-gs')?.textContent).toMatch(/Trophies:/);
    expect(pop.querySelector('.trophy-pop-gs')?.textContent).toMatch(/12/);
    expect(pop.querySelector('.trophy-pop-gs')?.textContent).toMatch(/33/);
    expect(pop.querySelector('.trophy-pop-gs')?.textContent).toMatch(/21 remaining/);
  });

  it('closes when the pointer leaves the pill', () => {
    const pill = makePill();
    hover(pill);
    const pop = document.getElementById('trophyPop');
    expect(pop.hidden).toBe(false);

    unhover(pill);
    expect(pop.hidden).toBe(true);
    expect(pill.getAttribute('aria-expanded')).toBe('false');
  });

  it('hides deep-sync footer for free tier', () => {
    isProMock.mockReturnValue(false);
    const pill = makePill({ store: 'xbox', gsCur: 10, gsTotal: 100 });
    hover(pill);
    const pop = document.getElementById('trophyPop');
    expect(pop.querySelector('.trophy-pop-meter')).toBeNull();
    expect(pop.querySelector('[data-deep-sync]')).toBeNull();
  });

  it('shows deep-sync button for pro on PSN/Xbox pills', () => {
    isProMock.mockReturnValue(true);
    const pill = makePill({ store: 'psn', key: 'psn:42', name: 'Test Game', troCur: 1, troTotal: 10 });
    hover(pill);
    const pop = document.getElementById('trophyPop');
    const btn = pop.querySelector('[data-deep-sync]');
    expect(btn).toBeTruthy();
    expect(btn.textContent).toBe('Deep sync');
    expect(btn.dataset.store).toBe('psn');
    expect(btn.dataset.key).toBe('psn:42');
    expect(pop.classList.contains('trophy-pop--interactive')).toBe(true);
  });

  it('does not show deep-sync for pro on non-PSN/Xbox stores', () => {
    isProMock.mockReturnValue(true);
    const pill = makePill({ store: 'steam', gsCur: 10, gsTotal: 100 });
    hover(pill);
    const pop = document.getElementById('trophyPop');
    expect(pop.querySelector('[data-deep-sync]')).toBeNull();
  });

  it('dispatches baklog:deep-sync when pro clicks Deep sync', () => {
    isProMock.mockReturnValue(true);
    const pill = makePill({ store: 'xbox', key: 'xbox:7', name: 'Halo' });
    hover(pill);
    const pop = document.getElementById('trophyPop');
    const events = [];
    document.addEventListener('baklog:deep-sync', (e) => events.push(e.detail));

    pop.querySelector('[data-deep-sync]').click();
    expect(events).toHaveLength(1);
    expect(events[0]).toEqual({ store: 'xbox', key: 'xbox:7', name: 'Halo' });
  });
});
