/**
 * BAKLOG landing page: interactive mega-hero demo with dummy data.
 * Self-contained; no app module imports.
 */
(function () {
  "use strict";

  const SPOTLIGHT_INTERVAL_MS = 7000;
  const SPOTLIGHT_FADE_MS = 300;
  const COUNT_ROLL_MS = 1000;
  const POPUP_SPAWN_MS = 70;
  const POPUP_CAP = 10;
  const POPUP_LIFETIME_MS = 700;
  const JITTER_PX = 4;

  const FINAL_COUNT = 2984;

  const STATS = {
    playedHrs: 412,
    backlogHrs: 2847,
    avgRating: 78,
    completion: 12,
    years: "3.9",
    wlDeals: 14,
    stores: 7,
  };

  const DEMO_STORE_KEYS = ["steam", "gog", "epic", "psn", "xbox", "nintendo", "itch"];
  const STORE_BRAND_COLORS = {
    steam: "#1b2838",
    epic: "#2f2d2e",
    gog: "#5100dc",
    psn: "#003791",
    xbox: "#107c10",
    nintendo: "#e60012",
    itch: "#fa5c5c",
  };
  const STORE_GLYPH_PATHS = {
    steam: "assets/store-logos/steam.svg",
    epic: "assets/store-logos/epic.svg",
    gog: "assets/store-logos/gog.svg",
    psn: "assets/store-logos/playstation.svg",
    xbox: "assets/store-logos/xbox.svg",
    nintendo: "assets/store-logos/nintendo.svg",
    itch: "assets/store-logos/itch.svg",
  };
  const STORE_LABELS = {
    steam: "Steam",
    gog: "GOG",
    epic: "Epic",
    psn: "PlayStation",
    xbox: "Xbox",
    nintendo: "Nintendo",
    itch: "itch.io",
  };

  const SPOTLIGHT_GAMES = [
    { title: "Emberfall", eyebrow: "Critically acclaimed", rating: 95, hltb: "42h", status: "in backlog", art: "assets/sample/hero-emberfall.webp", portrait: false },
    { title: "Ironveil", eyebrow: "Couch co-op", rating: 83, hltb: "10h", status: "in backlog", art: "assets/sample/cover-ironveil.webp", portrait: true },
    { title: "Rustbloom", eyebrow: "On sale now", rating: 92, saleCut: 80, price: "$5.99", art: "assets/sample/hero-rustbloom.webp", portrait: false },
    { title: "Ashlight Saga", eyebrow: "Highly rated", rating: 91, hltb: "55h", status: "in backlog", art: "assets/sample/cover-ashlight-saga.webp", portrait: true },
    { title: "Ashen Vale", eyebrow: "Long haul", rating: 90, hltb: "60h", status: "in progress", art: "assets/sample/hero-ashen-vale.webp", portrait: false },
    { title: "Encore", eyebrow: "Replay", rating: 93, hltb: "8h", status: "completed", art: "assets/sample/cover-encore.webp", portrait: true },
    { title: "Starbreak", eyebrow: "New frontier", rating: 90, hltb: "30h", status: "next up", art: "assets/sample/hero-starbreak.webp", portrait: false },
    { title: "Zephyr Edge", eyebrow: "Stylish action", rating: 88, hltb: "40h", status: "in backlog", art: "assets/sample/cover-zephyr-edge.webp", portrait: true },
    { title: "Tidewright", eyebrow: "New release", rating: 88, hltb: "26h", status: "next up", art: "assets/sample/hero-tidewright.webp", portrait: false },
    { title: "Hollowmaw", eyebrow: "Hidden gem", rating: 84, hltb: "14h", status: "in backlog", art: "assets/sample/cover-hollowmaw.webp", portrait: true },
    { title: "Dawnbanner", eyebrow: "Trending now", rating: 94, hltb: "38h", status: "in backlog", art: "assets/sample/hero-dawnbanner.webp", portrait: false },
    { title: "Apex Velocity", eyebrow: "Weekend-sized", rating: 89, hltb: "6h", status: "in backlog", art: "assets/sample/cover-apex-velocity.webp", portrait: true },
  ];

  const MARQUEE_ITEMS = [
    { icon: "S", cls: "is-emerald", label: "Steam", text: "<strong>257</strong> games synced" },
    { icon: "G", cls: "is-violet", label: "GOG", text: "<strong>673</strong> games synced" },
    { icon: "E", cls: "", label: "Epic", text: "<strong>259</strong> free claims counted" },
    { icon: "D", cls: "is-amber", label: "Deals", text: "<strong class=\"dash-marquee-cut deal-cut-huge\">-80%</strong> on Rustbloom" },
    { icon: "P", cls: "is-rose", label: "PSN", text: "<strong>597</strong> titles imported" },
    { icon: "B", cls: "is-emerald", label: "Backlog", text: "<strong>2,847h</strong> to clear" },
    { icon: "R", cls: "", label: "Reviews", text: "<strong>78%</strong> avg across library" },
    { icon: "I", cls: "is-violet", label: "itch.io", text: "<strong>1,044</strong> bundle keys" },
    { icon: "W", cls: "is-amber", label: "Wishlist", text: "<strong>14</strong> deals live now" },
    { icon: "C", cls: "is-emerald", label: "Complete", text: "<strong>12%</strong> of library finished" },
  ];

  const INSIGHTS = [
    "You own <strong>600</strong> games. You've played <strong>40</strong>.",
    "Every deal site tells you a game is <strong>80% off</strong>. BAKLOG tells you you already own it on Epic.",
    "<strong>2,847h</strong> backlog at 2h/day is <strong>3.9 years</strong> to clear.",
    "Connect once, hit Refresh, watch fetcher chips light up.",
    "There is no BAKLOG server to breach.",
  ];

  const reducedMotion = () =>
    window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function easeOutCubic(t) {
    return 1 - Math.pow(1 - t, 3);
  }

  function easeInOutCubic(t) {
    return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
  }

  function fmtCommas(n) {
    return Math.round(n).toLocaleString("en-US");
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function metaHtml(g) {
    if (g.saleCut != null) {
      const cutCls = g.saleCut >= 75 ? "deal-cut-huge" : g.saleCut >= 50 ? "deal-cut-big" : "";
      return `<strong>${g.rating}%</strong> review · <strong class="dash-spotlight-cut ${cutCls}">-${g.saleCut}%</strong> off · <strong class="dash-spotlight-price ${cutCls}">${escapeHtml(g.price)}</strong>`;
    }
    return `<strong>${g.rating}%</strong> review · <strong>${escapeHtml(g.hltb)}</strong> main · ${escapeHtml(g.status)}`;
  }

  function spotlightInnerHtml(g, animClass, eager = false) {
    const loadAttr = eager ? 'fetchpriority="high"' : 'loading="lazy"';
    const decodeAttr = 'decoding="async"';
    const alt = escapeHtml(g.title);
    const bg = g.portrait
      ? `<img class="dash-spotlight-art-bg is-loaded" src="${escapeHtml(g.art)}" alt="" aria-hidden="true" ${decodeAttr} ${loadAttr} />`
      : "";
    return `
      ${bg}
      <img class="dash-spotlight-art is-loaded" src="${escapeHtml(g.art)}" alt="${alt}" ${decodeAttr} ${loadAttr} />
      <div class="dash-spotlight-sheen" aria-hidden="true"></div>
      <div class="dash-spotlight-gradient" aria-hidden="true"></div>
      <div class="dash-spotlight-body">
        <span class="dash-spotlight-eyebrow">${escapeHtml(g.eyebrow)}</span>
        <span class="dash-spotlight-title">${escapeHtml(g.title)}</span>
        <span class="dash-spotlight-meta">${metaHtml(g)}</span>
      </div>`;
  }

  function buildMarqueeHtml() {
    const item = (m) =>
      `<span class="dash-marquee-item"><span class="dash-marquee-icon ${m.cls}">${m.icon}</span><span class="dash-marquee-label">${escapeHtml(m.label)}</span> ${m.text}</span>`;
    const track = MARQUEE_ITEMS.map(item).join("");
    return `<div class="dash-marquee-track">${track}${track}</div>`;
  }

  function buildStoreStripHtml() {
    const items = DEMO_STORE_KEYS.map((key) => {
      const color = STORE_BRAND_COLORS[key];
      const glyph = STORE_GLYPH_PATHS[key];
      const label = STORE_LABELS[key];
      return `<span role="listitem"><span class="store-logo store-logo--glyph store-logo--md" style="--store-logo-bg:${color};--store-logo-glyph:url('${glyph}')" title="${escapeHtml(label)}" aria-label="${escapeHtml(label)}"><span class="store-logo-glyph" aria-hidden="true"></span></span></span>`;
    }).join("");
    return `<div class="dash-hero-stores" aria-label="Stores in your library"><div class="store-logo-strip store-logo-strip--md" role="list" aria-label="Stores in your library">${items}</div></div>`;
  }

  function buildMegaHtml() {
    return `
      <div class="dash-mega dash-mega--has-spotlight" id="dashboardMega">
        <div class="dash-mega-hero">
          <div class="dash-spotlight-host">
            <div class="dash-spotlight dash-spotlight--multi has-portrait-art portrait-anim-1" id="dashboardSpotlight" role="group" aria-roledescription="carousel" aria-label="Spotlight game"></div>
            <div class="dash-spotlight-nav" id="spotlightNav">
              <button type="button" class="dash-spotlight-nav-btn" data-spotlight-nav="prev" aria-label="Previous spotlight" title="Previous">‹</button>
              <button type="button" class="dash-spotlight-nav-btn" data-spotlight-nav="next" aria-label="Next spotlight" title="Next">›</button>
            </div>
          </div>
          <div class="dash-hero-eyebrow">Your library</div>
          <span class="library-count-host" data-libcount-host>
            <span class="dash-hero-number" id="dashHeroCount">0</span>
          </span>
          <div class="dash-hero-sub">games owned across ${STATS.stores} stores</div>
          ${buildStoreStripHtml()}
          <div class="dash-hero-tagline">
            <span><strong>${STATS.completion}%</strong> complete</span>
            <span class="sep">·</span>
            <span><strong>${STATS.years}</strong> yrs to clear at 2h/day</span>
            <span class="sep">·</span>
            <span><strong>${STATS.wlDeals}</strong> deals live</span>
          </div>
          <div class="dash-hero-pillars">
            <div class="dash-hero-pillar">
              <div class="dash-hero-pillar-value" id="dashHeroPlayed">0h</div>
              <div class="dash-hero-pillar-label">Played</div>
            </div>
            <div class="dash-hero-pillar">
              <div class="dash-hero-pillar-value" id="dashHeroBacklog">0h</div>
              <div class="dash-hero-pillar-label">Backlog</div>
            </div>
            <div class="dash-hero-pillar">
              <div class="dash-hero-pillar-value" id="dashHeroAvg">0%</div>
              <div class="dash-hero-pillar-label">Avg review</div>
            </div>
          </div>
          <span id="dashboardInsight" class="dash-insight" aria-live="polite"></span>
        </div>
        <div class="dash-marquee">${buildMarqueeHtml()}</div>
        <div class="dash-mega-divider" aria-hidden="true"></div>
        <div class="dash-ribbon">
          <div class="dash-ribbon-tile">
            <div class="dash-ribbon-eyebrow">Library by store</div>
            <div class="dash-ribbon-chart"><canvas id="chartStoreDonut"></canvas></div>
            <div class="dash-ribbon-headline" id="ribbonStoreHeadline"><strong>Steam</strong> leads at 40%</div>
          </div>
          <div class="dash-ribbon-tile">
            <div class="dash-ribbon-eyebrow">Status breakdown</div>
            <div class="dash-ribbon-chart"><canvas id="chartStatusDonut"></canvas></div>
            <div class="dash-ribbon-headline" id="ribbonStatusHeadline"><strong>57%</strong> still in backlog</div>
          </div>
          <div class="dash-ribbon-tile">
            <div class="dash-ribbon-eyebrow">Review sentiment</div>
            <div class="dash-ribbon-chart"><canvas id="chartReviewDonut"></canvas></div>
            <div class="dash-ribbon-headline" id="ribbonReviewHeadline">Mostly <strong>very positive</strong></div>
          </div>
        </div>
      </div>`;
  }

  // --- Count-up + popups ---
  let countDemoRan = false;
  let countTimers = [];
  let countLoopActive = false;
  let countNode = null;
  let countFormat = fmtCommas;
  let countFrom = 0;
  let countTo = 0;
  let countStart = 0;
  let countDur = COUNT_ROLL_MS;

  function countTick(now) {
    if (!countNode) {
      countLoopActive = false;
      return;
    }
    const t = Math.min(1, (now - countStart) / countDur);
    const v = countFrom + (countTo - countFrom) * easeInOutCubic(t);
    countNode.textContent = countFormat(v);
    if (t < 1) {
      requestAnimationFrame(countTick);
    } else {
      countNode.textContent = countFormat(countTo);
      countLoopActive = false;
    }
  }

  function clearCountTimers() {
    countTimers.forEach((id) => clearTimeout(id));
    countTimers = [];
  }

  function spawnPopups(host, total, count) {
    if (!host || reducedMotion()) return;
    const base = Math.floor(total / count);
    let remaining = total;
    for (let i = 0; i < count; i++) {
      const value = i === count - 1 ? remaining : Math.max(1, base);
      remaining -= value;
      const delay = i * POPUP_SPAWN_MS;
      const id = setTimeout(() => {
        if (!host.isConnected) return;
        const el = document.createElement("span");
        el.className = "library-count-popup";
        el.setAttribute("aria-hidden", "true");
        el.textContent = `+${value.toLocaleString("en-US")}`;
        const dx = Math.random() * JITTER_PX * 2 - JITTER_PX * 0.5;
        el.style.setProperty("--baklog-dx", `${dx.toFixed(1)}px`);
        host.appendChild(el);
        const reap = setTimeout(() => el.remove(), POPUP_LIFETIME_MS + 200);
        el.addEventListener("animationend", () => {
          clearTimeout(reap);
          el.remove();
        }, { once: true });
      }, delay);
      countTimers.push(id);
    }
  }

  function flashCountUp(node, from, to, format, opts = {}) {
    if (!node) return;
    const safeFrom = Number.isFinite(from) ? from : 0;
    const safeTo = Number.isFinite(to) ? to : safeFrom;
    if (safeTo === safeFrom) {
      node.textContent = format(safeTo);
      return;
    }
    if (reducedMotion()) {
      node.textContent = format(safeTo);
      return;
    }
    const durationMs = opts.durationMs || COUNT_ROLL_MS;
    const host = opts.popups !== false ? node.closest("[data-libcount-host]") : null;
    if (host && safeTo > safeFrom) {
      const delta = safeTo - safeFrom;
      const count = Number.isFinite(opts.popupCount) ? opts.popupCount : Math.min(delta, POPUP_CAP);
      spawnPopups(host, delta, count);
    }
    countNode = node;
    countFormat = format;
    countFrom = safeFrom;
    countTo = safeTo;
    countDur = durationMs;
    countStart = performance.now();
    if (!countLoopActive) {
      countLoopActive = true;
      requestAnimationFrame(countTick);
    }
  }

  function animatePillar(id, to, suffix) {
    const node = document.getElementById(id);
    if (!node) return;
    if (reducedMotion()) {
      node.textContent = `${fmtCommas(to)}${suffix}`;
      return;
    }
    const start = performance.now();
    const dur = 1000;
    function tick(now) {
      const t = Math.min(1, (now - start) / dur);
      const v = to * easeOutCubic(t);
      node.textContent = `${fmtCommas(v)}${suffix}`;
      if (t < 1) requestAnimationFrame(tick);
      else node.textContent = `${fmtCommas(to)}${suffix}`;
    }
    requestAnimationFrame(tick);
  }

  function reserveCountWidth(hero) {
    const prev = hero.textContent;
    hero.style.minWidth = "";
    hero.textContent = fmtCommas(FINAL_COUNT);
    const w = hero.getBoundingClientRect().width;
    if (w) {
      hero.style.minWidth = `${Math.ceil(w)}px`;
      hero.style.textAlign = "right";
    }
    hero.textContent = prev;
  }

  function runCountDemo() {
    if (countDemoRan) return;
    countDemoRan = true;
    const hero = document.getElementById("dashHeroCount");
    if (!hero) return;
    reserveCountWidth(hero);
    hero.textContent = "0";
    const climbMs = 8000;
    flashCountUp(hero, 0, FINAL_COUNT, fmtCommas, { popups: true, durationMs: climbMs, popupCount: 10 });
    countTimers.push(setTimeout(() => {
      animatePillar("dashHeroPlayed", STATS.playedHrs, "h");
      animatePillar("dashHeroBacklog", STATS.backlogHrs, "h");
      animatePillar("dashHeroAvg", STATS.avgRating, "%");
    }, climbMs + 300));
  }

  function replayCountDemo() {
    countDemoRan = false;
    clearCountTimers();
    document.querySelectorAll(".library-count-popup").forEach((el) => el.remove());
    const hero = document.getElementById("dashHeroCount");
    if (hero) hero.textContent = "0";
    ["dashHeroPlayed", "dashHeroBacklog", "dashHeroAvg"].forEach((id) => {
      const n = document.getElementById(id);
      if (n) n.textContent = id === "dashHeroAvg" ? "0%" : "0h";
    });
    runCountDemo();
  }

  // --- Spotlight ---
  let spotlightIndex = 0;
  let spotlightTimer = null;
  let spotlightFadeTimer = null;
  let spotlightPaused = false;

  function animClassFor(i) {
    return `portrait-anim-${(i % 4) + 1}`;
  }

  function applySpotlight(g, i) {
    const el = document.getElementById("dashboardSpotlight");
    if (!el) return;
    const portrait = g.portrait;
    el.className = "dash-spotlight dash-spotlight--multi" +
      (portrait ? ` has-portrait-art ${animClassFor(i)}` : "");
    el.innerHTML = spotlightInnerHtml(g, animClassFor(i));
    wireSpotlightHover(el);
  }

  function fadeToSpotlight(next, i) {
    const el = document.getElementById("dashboardSpotlight");
    if (!el) return;
    el.classList.add("is-fading");
    if (spotlightFadeTimer) clearTimeout(spotlightFadeTimer);
    spotlightFadeTimer = setTimeout(() => {
      applySpotlight(next, i);
      el.classList.remove("is-fading");
      spotlightFadeTimer = null;
    }, SPOTLIGHT_FADE_MS);
  }

  function stepSpotlight(delta) {
    const len = SPOTLIGHT_GAMES.length;
    if (len <= 1) return;
    spotlightIndex = (spotlightIndex + delta + len) % len;
    fadeToSpotlight(SPOTLIGHT_GAMES[spotlightIndex], spotlightIndex);
    resetSpotlightTimer();
  }

  function resetSpotlightTimer() {
    if (spotlightTimer) clearInterval(spotlightTimer);
    if (SPOTLIGHT_GAMES.length <= 1 || reducedMotion()) return;
    spotlightTimer = setInterval(() => {
      if (spotlightPaused) return;
      stepSpotlight(1);
    }, SPOTLIGHT_INTERVAL_MS);
  }

  function wireSpotlightHover(el) {
    if (!el || el.dataset.hoverWired) return;
    el.dataset.hoverWired = "1";

    el.addEventListener("mouseenter", () => { spotlightPaused = true; });
    el.addEventListener("mouseleave", () => { spotlightPaused = false; });

    const MAX_YAW = 12;
    const MAX_PITCH = 7;
    const HOVER_SCALE = 1.03;
    const BG_BASE_SCALE = 1.08;
    const EASE = 0.14;
    let hovering = false;
    let rafId = null;
    let lastPointer = null;
    const cur = { rx: 0, ry: 0, sc: 1, sx: 0.5, op: 0 };
    const target = { rx: 0, ry: 0, sc: 1, sx: 0.5, op: 0 };

    const portraitArt = () =>
      el.classList.contains("has-portrait-art") ? el.querySelector(".dash-spotlight-art") : null;
    const portraitBg = () =>
      el.classList.contains("has-portrait-art") ? el.querySelector(".dash-spotlight-art-bg") : null;
    const portraitSheen = () =>
      el.classList.contains("has-portrait-art") ? el.querySelector(".dash-spotlight-sheen") : null;

    const writeTransform = (art) => {
      art.style.transform =
        `perspective(900px) rotateY(${cur.ry.toFixed(2)}deg) rotateX(${cur.rx.toFixed(2)}deg) scale(${cur.sc.toFixed(4)}) translateZ(0)`;
      const bg = portraitBg();
      if (bg) {
        bg.style.transform = `scale(${(BG_BASE_SCALE * cur.sc).toFixed(4)}) translateZ(0)`;
      }
      el.style.setProperty("--sheen-x", `${(cur.sx * 100).toFixed(2)}%`);
      el.style.setProperty("--sheen-op", cur.op.toFixed(3));
    };

    const clearTransforms = () => {
      const art = portraitArt();
      const bg = portraitBg();
      if (art) art.style.transform = "";
      if (bg) bg.style.transform = "";
      el.style.removeProperty("--sheen-x");
      el.style.removeProperty("--sheen-op");
    };

    const frame = () => {
      const art = portraitArt();
      if (!art) {
        rafId = null;
        clearTransforms();
        el.classList.remove("is-tilting");
        return;
      }
      cur.rx += (target.rx - cur.rx) * EASE;
      cur.ry += (target.ry - cur.ry) * EASE;
      cur.sc += (target.sc - cur.sc) * EASE;
      cur.sx += (target.sx - cur.sx) * EASE;
      cur.op += (target.op - cur.op) * EASE;
      writeTransform(art);
      const settled =
        Math.abs(target.rx - cur.rx) < 0.02 &&
        Math.abs(target.ry - cur.ry) < 0.02 &&
        Math.abs(target.sc - cur.sc) < 0.0008 &&
        Math.abs(target.sx - cur.sx) < 0.005 &&
        Math.abs(target.op - cur.op) < 0.01;
      if (!hovering && settled) {
        cur.rx = cur.ry = 0;
        cur.sc = 1;
        cur.sx = 0.5;
        cur.op = 0;
        clearTransforms();
        el.classList.remove("is-tilting");
        rafId = null;
        return;
      }
      rafId = requestAnimationFrame(frame);
    };

    const startLoop = () => {
      if (rafId == null) rafId = requestAnimationFrame(frame);
    };

    const updateTilt = (clientX, clientY) => {
      const art = portraitArt();
      if (!art) return;
      const r = art.getBoundingClientRect();
      if (!r.width || !r.height) return;
      const px = Math.max(-0.5, Math.min(0.5, (clientX - r.left) / r.width - 0.5));
      const py = Math.max(-0.5, Math.min(0.5, (clientY - r.top) / r.height - 0.5));
      target.ry = px * MAX_YAW;
      target.rx = -py * MAX_PITCH;
      const sheen = portraitSheen();
      const sr = sheen?.getBoundingClientRect();
      target.sx = sr && sr.width ? Math.max(0, Math.min(1, (clientX - sr.left) / sr.width)) : px + 0.5;
    };

    const endTilt = () => {
      hovering = false;
      target.rx = target.ry = 0;
      target.sc = 1;
      target.op = 0;
      startLoop();
    };

    el.addEventListener("pointerenter", (e) => {
      if (e.pointerType === "touch" || reducedMotion()) return;
      lastPointer = { x: e.clientX, y: e.clientY };
      if (!portraitArt()) return;
      hovering = true;
      target.sc = HOVER_SCALE;
      target.op = 1;
      el.classList.add("is-tilting");
      updateTilt(e.clientX, e.clientY);
      cur.sx = target.sx;
      startLoop();
    });

    el.addEventListener("pointermove", (e) => {
      if (e.pointerType === "touch" || reducedMotion() || !hovering) return;
      lastPointer = { x: e.clientX, y: e.clientY };
      updateTilt(e.clientX, e.clientY);
      startLoop();
    });

    el.addEventListener("pointerleave", endTilt);
    el.addEventListener("pointercancel", endTilt);

    el.addEventListener("keydown", (e) => {
      if (e.key === "ArrowLeft") { e.preventDefault(); stepSpotlight(-1); }
      else if (e.key === "ArrowRight") { e.preventDefault(); stepSpotlight(1); }
    });
  }

  function wireSpotlightNav() {
    const nav = document.getElementById("spotlightNav");
    if (!nav || nav.dataset.navWired) return;
    nav.dataset.navWired = "1";
    nav.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-spotlight-nav]");
      if (!btn) return;
      e.preventDefault();
      stepSpotlight(btn.dataset.spotlightNav === "prev" ? -1 : 1);
    });
  }

  // --- Insight rotation ---
  let insightIndex = 0;
  let insightTimer = null;

  function rotateInsight() {
    const el = document.getElementById("dashboardInsight");
    if (!el || !INSIGHTS.length) return;
    el.classList.remove("is-visible");
    setTimeout(() => {
      el.innerHTML = INSIGHTS[insightIndex % INSIGHTS.length];
      insightIndex++;
      el.classList.add("is-visible");
    }, reducedMotion() ? 0 : 200);
  }

  function startInsightRotation() {
    rotateInsight();
    if (reducedMotion()) return;
    insightTimer = setInterval(rotateInsight, 6000);
  }

  // --- Charts ---
  // Dummy data keyed to the app's dashboard color maps (js/dashboard-shared.js
  // DASH_STORE_COLORS / DASH_STATUS_COLORS / DASH_REVIEW_COLORS) so the landing
  // donuts read like the real dashboard ribbon.
  const STORE_DONUT = {
    labels: ["Steam", "GOG", "Epic", "PSN", "Xbox", "Amazon", "itch.io"],
    data: [40, 22, 14, 12, 6, 4, 2],
    colors: ["#66c0f4", "#5100dc", "#cfd2d6", "#003791", "#107c10", "#ff9900", "#fa5c5c"],
  };
  const STATUS_DONUT = {
    labels: ["Backlog", "Playing", "Finished", "Next", "Skip"],
    data: [57, 18, 12, 9, 4],
    colors: ["#ef4444", "#facc15", "#22c55e", "#38bdf8", "#475569"],
  };
  const REVIEW_DONUT = {
    labels: ["Overwhelmingly Positive", "Very Positive", "Mostly Positive", "Mixed"],
    data: [28, 42, 24, 6],
    colors: ["#22c55e", "#34d399", "#86efac", "#fbbf24"],
  };

  function makeDonut(canvasId, spec) {
    const canvas = document.getElementById(canvasId);
    if (!canvas || typeof Chart === "undefined") return null;
    return new Chart(canvas, {
      type: "doughnut",
      data: {
        labels: spec.labels,
        datasets: [{
          data: spec.data,
          backgroundColor: spec.colors,
          borderWidth: 0,
          hoverOffset: 4,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            position: "right",
            labels: { color: "#ffffff", boxWidth: 12, padding: 8, font: { size: 11 } },
          },
        },
        animation: reducedMotion() ? false : { duration: 800 },
      },
    });
  }

  function initCharts() {
    if (typeof Chart !== "undefined") {
      Chart.defaults.color = "#94a3b8";
      Chart.defaults.borderColor = "#334155";
    }
    makeDonut("chartStoreDonut", STORE_DONUT);
    makeDonut("chartStatusDonut", STATUS_DONUT);
    makeDonut("chartReviewDonut", REVIEW_DONUT);
  }

  // --- Init ---
  function init() {
    const mount = document.getElementById("demoMount");
    if (!mount) return;
    mount.innerHTML = buildMegaHtml();

    applySpotlight(SPOTLIGHT_GAMES[0], 0);
    wireSpotlightNav();
    resetSpotlightTimer();
    startInsightRotation();
    requestAnimationFrame(() => initCharts());

    const heroCount = document.getElementById("dashHeroCount");
    if (heroCount) {
      heroCount.style.cursor = "pointer";
      heroCount.title = "Click to replay the library import demo";
      heroCount.setAttribute("tabindex", "0");
      heroCount.setAttribute("role", "button");
      heroCount.setAttribute("aria-label", "Replay library import demo");
      heroCount.addEventListener("click", replayCountDemo);
      heroCount.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          replayCountDemo();
        }
      });
    }

    const demoSection = document.getElementById("demo");
    if (demoSection && "IntersectionObserver" in window) {
      const obs = new IntersectionObserver(
        (entries) => {
          if (entries.some((e) => e.isIntersecting)) {
            runCountDemo();
            obs.disconnect();
          }
        },
        { threshold: 0.25 }
      );
      obs.observe(demoSection);
    } else {
      runCountDemo();
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
