/** Constant px/s marquee scroll. Tune via --marquee-px-per-sec in CSS. */

export const MARQUEE_PX_PER_SEC = 24;

function pxPerSec() {
  const raw = getComputedStyle(document.documentElement).getPropertyValue('--marquee-px-per-sec').trim();
  const n = parseFloat(raw);
  return Number.isFinite(n) && n > 0 ? n : MARQUEE_PX_PER_SEC;
}

function scopeEl(rootEl) {
  return rootEl && typeof rootEl.querySelector === 'function' ? rootEl : document;
}

/** Set --marquee-duration from measured track width for constant px/s. */
export function applyMarqueeSpeed(rootEl = document) {
  const track = scopeEl(rootEl).querySelector('.dash-marquee-track');
  if (!track) return;
  const copyWidth = track.scrollWidth / 2;
  if (!copyWidth) return;
  track.style.setProperty('--marquee-duration', `${copyWidth / pxPerSec()}s`);
}

/** Measure after layout, re-measure on track resize; returns disconnect(). */
export function observeMarqueeSpeed(rootEl = document) {
  let ro = null;
  let rafId = 0;

  const apply = () => applyMarqueeSpeed(rootEl);

  const schedule = () => {
    if (rafId) cancelAnimationFrame(rafId);
    rafId = requestAnimationFrame(() => {
      rafId = requestAnimationFrame(() => {
        rafId = 0;
        apply();
        const track = scopeEl(rootEl).querySelector('.dash-marquee-track');
        if (!track || typeof ResizeObserver === 'undefined') return;
        if (ro) ro.disconnect();
        ro = new ResizeObserver(apply);
        ro.observe(track);
      });
    });
  };

  schedule();

  return () => {
    if (rafId) cancelAnimationFrame(rafId);
    rafId = 0;
    if (ro) {
      ro.disconnect();
      ro = null;
    }
  };
}
