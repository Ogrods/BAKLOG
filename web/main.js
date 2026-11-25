/**
 * Landing page utilities: footer year, waitlist form, magic-moment scrub, product lightbox.
 */
(function () {
  "use strict";

  const yearEl = document.getElementById("year");
  if (yearEl) yearEl.textContent = String(new Date().getFullYear());

  const form = document.getElementById("waitlist");
  if (form) {
    const emailEl = document.getElementById("email");
    const btn = document.getElementById("submitBtn");
    const msg = document.getElementById("formMsg");
    const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      msg.className = "form-msg";
      msg.textContent = "";

      const email = emailEl.value.trim();
      if (!EMAIL_RE.test(email)) {
        msg.className = "form-msg err";
        msg.textContent = "Please enter a valid email.";
        emailEl.focus();
        return;
      }

      const website = form.elements["website"].value;
      btn.disabled = true;
      const original = btn.textContent;
      btn.textContent = "Sending…";

      try {
        const res = await fetch("/api/subscribe", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, website }),
        });
        if (!res.ok) throw new Error("bad status");
        form.querySelector(".waitlist-row").remove();
        form.querySelector(".form-reassure").remove();
        msg.className = "form-msg ok";
        msg.textContent =
          "Check your inbox for the download link. The open beta is ready now.";
      } catch {
        btn.disabled = false;
        btn.textContent = original;
        msg.className = "form-msg err";
        msg.textContent = "Something went wrong. Please try again in a moment.";
      }
    });
  }

  /** Sticky Connect → chips → count scrub for #how (desktop). Mobile CSS shows all stages. */
  function initMagicScrub() {
    const root = document.querySelector("[data-magic-scrub]");
    if (!root) return;

    const track = root.querySelector(".magic-scrub-track");
    const stages = Array.from(root.querySelectorAll(".magic-stage"));
    const shots = Array.from(root.querySelectorAll("[data-magic-shot]"));
    const visual = root.querySelector(".magic-visual");
    const chips = Array.from(root.querySelectorAll(".magic-chip"));
    const bar = root.querySelector("[data-magic-bar]");
    if (!track || stages.length < 3) return;

    const reduceMq = window.matchMedia
      ? window.matchMedia("(prefers-reduced-motion: reduce)")
      : { matches: false, addEventListener: () => {} };
    const mobileMq = window.matchMedia
      ? window.matchMedia("(max-width: 768px)")
      : { matches: false, addEventListener: () => {} };

    let raf = 0;
    let lastStage = -1;
    let scrubbing = false;

    function setShot(stage) {
      shots.forEach((el, i) => {
        el.classList.toggle("is-active", i === stage);
      });
    }

    function showAllStatic() {
      stages.forEach((el) => el.classList.add("is-active"));
      chips.forEach((chip) => chip.classList.add("is-on"));
      if (bar) bar.style.width = "100%";
      setShot(Math.max(0, shots.length - 1));
      if (visual) visual.style.setProperty("--magic-drift", "0");
    }

    function applyProgress(p) {
      const clamped = Math.max(0, Math.min(1, p));
      if (bar) bar.style.width = `${(clamped * 100).toFixed(1)}%`;
      if (visual) {
        // Drift about ±4% across the scrub so the frame feels tied to scroll.
        visual.style.setProperty("--magic-drift", ((clamped - 0.5) * 8).toFixed(2));
      }

      const stage = clamped < 0.22 ? 0 : clamped < 0.55 ? 1 : 2;
      if (stage !== lastStage) {
        lastStage = stage;
        stages.forEach((el, i) => {
          el.classList.toggle("is-active", i === stage);
        });
        setShot(stage);
      }

      const chipProgress = Math.max(0, (clamped - 0.12) / 0.35);
      chips.forEach((chip, i) => {
        const on = chipProgress > (i + 0.15) / chips.length;
        chip.classList.toggle("is-on", on);
      });
    }

    function onScroll() {
      if (!scrubbing) return;
      if (raf) return;
      raf = requestAnimationFrame(() => {
        raf = 0;
        const rect = track.getBoundingClientRect();
        const view = Math.max(1, window.innerHeight);
        // Start scrubbing once the track top reaches ~35% down the viewport (not only at top=0).
        const startOffset = view * 0.35;
        const total = Math.max(1, rect.height - view + startOffset);
        const scrolled = Math.min(total, Math.max(0, -rect.top + startOffset));
        applyProgress(scrolled / total);
      });
    }

    function syncMode() {
      const staticMode = reduceMq.matches || mobileMq.matches;
      scrubbing = !staticMode;
      lastStage = -1;
      if (staticMode) {
        showAllStatic();
      } else {
        onScroll();
      }
    }

    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll, { passive: true });
    if (reduceMq.addEventListener) {
      reduceMq.addEventListener("change", syncMode);
      mobileMq.addEventListener("change", syncMode);
    } else if (reduceMq.addListener) {
      reduceMq.addListener(syncMode);
      mobileMq.addListener(syncMode);
    }
    syncMode();
  }

  /** Shared product-thumbnail lightbox (hero peek + how-after proof). */
  function initProductLightbox() {
    const dialog = document.getElementById("productLightbox");
    const img = document.getElementById("productLightboxImg");
    if (!dialog || !img || typeof dialog.showModal !== "function") return;

    let lastTrigger = null;

    function openFrom(trigger) {
      const href = trigger.getAttribute("href");
      if (!href) return;
      const thumb = trigger.querySelector("img");
      img.src = href;
      img.alt = (thumb && thumb.getAttribute("alt")) || "Product screenshot";
      lastTrigger = trigger;
      dialog.showModal();
      const closeBtn = dialog.querySelector("[data-lightbox-close]");
      if (closeBtn) closeBtn.focus();
    }

    function closeLightbox() {
      if (!dialog.open) return;
      dialog.close();
    }

    document.addEventListener("click", (e) => {
      const trigger = e.target.closest("a[data-lightbox]");
      if (!trigger) return;
      e.preventDefault();
      openFrom(trigger);
    });

    dialog.addEventListener("click", (e) => {
      if (e.target === dialog || e.target.closest("[data-lightbox-close]")) {
        closeLightbox();
      }
    });

    dialog.addEventListener("close", () => {
      img.removeAttribute("src");
      img.alt = "";
      if (lastTrigger && typeof lastTrigger.focus === "function") {
        lastTrigger.focus();
      }
      lastTrigger = null;
    });
  }

  function boot() {
    initMagicScrub();
    initProductLightbox();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
