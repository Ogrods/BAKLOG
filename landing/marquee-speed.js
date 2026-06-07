/** Keep in sync with js/marquee-speed.js */
(function (global) {
  const MARQUEE_PX_PER_SEC = 24;

  function pxPerSec() {
    const raw = getComputedStyle(document.documentElement).getPropertyValue("--marquee-px-per-sec").trim();
    const n = parseFloat(raw);
    return Number.isFinite(n) && n > 0 ? n : MARQUEE_PX_PER_SEC;
  }

  function scopeEl(rootEl) {
    return rootEl && typeof rootEl.querySelector === "function" ? rootEl : document;
  }

  function applyMarqueeSpeed(rootEl) {
    const track = scopeEl(rootEl).querySelector(".dash-marquee-track");
    if (!track) return;
    // #region agent log
    const __t0 = (typeof performance !== "undefined" ? performance.now() : Date.now());
    const copyWidth = track.scrollWidth / 2;
    const __t1 = (typeof performance !== "undefined" ? performance.now() : Date.now());
    try {
      const g = (typeof globalThis !== "undefined" ? globalThis : window);
      g.__dbgMarqueeApply = (g.__dbgMarqueeApply || 0) + 1;
      const ms = __t1 - __t0;
      if (ms > (g.__dbgMarqueeMaxMs || 0)) g.__dbgMarqueeMaxMs = ms;
      if (document.documentElement.classList.contains("ui-resizing")) {
        g.__dbgMarqueeApplyDuringResize = (g.__dbgMarqueeApplyDuringResize || 0) + 1;
      }
    } catch (_) {}
    // #endregion
    if (!copyWidth) return;
    track.style.setProperty("--marquee-duration", `${copyWidth / pxPerSec()}s`);
  }

  function observeMarqueeSpeed(rootEl) {
    let ro = null;
    let rafId = 0;

    const apply = () => applyMarqueeSpeed(rootEl);

    const schedule = () => {
      if (rafId) cancelAnimationFrame(rafId);
      rafId = requestAnimationFrame(() => {
        rafId = requestAnimationFrame(() => {
          rafId = 0;
          apply();
          const track = scopeEl(rootEl).querySelector(".dash-marquee-track");
          if (!track || typeof ResizeObserver === "undefined") return;
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

  global.BaklogMarquee = {
    MARQUEE_PX_PER_SEC,
    applyMarqueeSpeed,
    observeMarqueeSpeed,
  };
})(typeof globalThis !== "undefined" ? globalThis : window);
