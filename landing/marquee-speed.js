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
    const scope = scopeEl(rootEl);
    const track = scope.querySelector(".dash-marquee-track");
    if (!track) return;
    const firstCopy = track.querySelector(".dash-marquee-copy");
    const copyWidth = firstCopy ? firstCopy.scrollWidth : track.scrollWidth / 2;
    if (!copyWidth) return;
    // One copy must fill the bar for the -50% loop to be seamless. When the
    // chips don't fill it, animating leaves a visible gap/jump — mark the
    // marquee static (centered, no scroll) instead.
    const marquee = scope.querySelector(".dash-marquee");
    const containerWidth = marquee ? marquee.clientWidth : 0;
    const fits = containerWidth > 0 && copyWidth <= containerWidth;
    if (marquee) marquee.classList.toggle("dash-marquee--static", fits);
    if (fits) {
      track.style.removeProperty("--marquee-duration");
      return;
    }
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
