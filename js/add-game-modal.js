import { state } from './state.js';
import { escapeHtml } from './dom-util.js';
import {
  loadManualGames,
  saveManualGames,
  addManualGame,
  setGameHidden,
} from './personal-storage.js';
import { refreshAfterManualChange } from './library-load.js';
import { download } from './filters-ui.js';
import {
  findDuplicateMatch,
  duplicateMatchLabel,
  duplicateMatchKey,
} from './game-duplicate.js';
import { flashGameRow } from './table-ui.js';
import { bindEscapeClose, trapFocus } from './focus-trap.js';

let addGameTarget = "library";
let _pendingAdd = null;
/** @type {(() => void) | null} */
let _bypassFor = null;
let _addGameModalRelease = null;

export function setAddGameTarget(target) {
  addGameTarget = target === "wishlist" ? "wishlist" : target === "itch" ? "itch" : "library";
  document.querySelectorAll(".add-target-btn").forEach(b => {
    b.classList.toggle("active", b.dataset.target === addGameTarget);
  });
  document.getElementById("addGameWishlistFields").classList.toggle("hidden", addGameTarget !== "wishlist");
  const titleEl = document.getElementById("addGameModalTitle");
  const hint = document.getElementById("addGameHint");
  if (addGameTarget === "wishlist") {
    titleEl.textContent = "Add to wishlist";
    hint.textContent = "Tracking a deal? Add an optional price and/or discount % and store URL. Discount-only entries still match On sale / Min discount filters even without a price.";
  } else if (addGameTarget === "itch") {
    titleEl.textContent = "Add to itch.io";
    hint.textContent = "Type a title and click Search Steam to import cover/rating, or save without a match. The game will be saved under your chosen platform.";
  } else {
    titleEl.textContent = "Add a game";
    hint.textContent = "Type a title and click Search Steam. Pick the closest match to import its cover, Steam rating, and store link. The game will be saved under your chosen platform.";
  }
}

function openAddGameModal() {
  const m = document.getElementById("addGameModal");
  const dialog = m.querySelector('[role="dialog"]') || m;
  m.classList.remove("hidden");
  m.classList.add("flex");
  setAddGameTarget(state.activeView === "wishlist" ? "wishlist" : state.activeView === "itch" ? "itch" : "library");
  _addGameModalRelease?.();
  const releaseTrap = trapFocus(dialog);
  const releaseEsc = bindEscapeClose(dialog, closeAddGameModal);
  _addGameModalRelease = () => {
    releaseTrap();
    releaseEsc();
    _addGameModalRelease = null;
  };
  document.getElementById("addGameTitle").focus();
}

function hideDuplicateWarn() {
  const box = document.getElementById("addGameDuplicateWarn");
  if (box) box.classList.add("hidden");
  _pendingAdd = null;
}

function showDuplicateWarn(match, onProceed) {
  const box = document.getElementById("addGameDuplicateWarn");
  const text = document.getElementById("addGameDuplicateText");
  if (!box || !text) {
    onProceed();
    return;
  }
  const where = addGameTarget === "wishlist" ? "wishlist" : "library";
  text.innerHTML = `This looks like <strong>${escapeHtml(duplicateMatchLabel(match, addGameTarget))}</strong> already in your ${where}.`;
  _pendingAdd = onProceed;
  box.classList.remove("hidden");
}

function closeAddGameModal() {
  _addGameModalRelease?.();
  const m = document.getElementById("addGameModal");
  m.classList.add("hidden");
  m.classList.remove("flex");
  document.getElementById("addGameTitle").value = "";
  document.getElementById("addGameResults").innerHTML = "";
  document.getElementById("addGameStatus").textContent = "";
  document.getElementById("addGameWishPrice").value = "";
  document.getElementById("addGameWishDiscount").value = "";
  document.getElementById("addGameWishUrl").value = "";
  hideDuplicateWarn();
  _bypassFor = null;
}

function runWithDuplicateCheck(title, proceed) {
  if (_bypassFor === proceed) {
    _bypassFor = null;
    proceed();
    return;
  }
  _bypassFor = null;
  const match = findDuplicateMatch(title, addGameTarget);
  if (!match) {
    hideDuplicateWarn();
    proceed();
    return;
  }
  showDuplicateWarn(match, proceed);
}

async function steamSearch(term) {
  const url = `https://store.steampowered.com/api/storesearch/?term=${encodeURIComponent(term)}&l=english&cc=US`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Steam search HTTP ${res.status}`);
  const data = await res.json();
  return (data.items || []).slice(0, 6);
}

async function steamAppReviews(appid) {
  const url = `https://store.steampowered.com/appreviews/${appid}?json=1&language=all&purchase_type=all&num_per_page=0`;
  try {
    const res = await fetch(url);
    if (!res.ok) return null;
    const data = await res.json();
    if (!data.success || !data.query_summary) return null;
    const q = data.query_summary;
    return {
      steam_review_percent: q.total_reviews > 0 ? Math.round((q.total_positive / q.total_reviews) * 100) : null,
      steam_review_count: q.total_reviews || 0,
      steam_review_desc: q.review_score_desc || null,
    };
  } catch { return null; }
}

function manualSlug(title) {
  return "manual-" + String(title).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 60);
}

function readWishlistFields() {
  const priceRaw = document.getElementById("addGameWishPrice").value.trim();
  const discountRaw = document.getElementById("addGameWishDiscount").value.trim();
  const url = document.getElementById("addGameWishUrl").value.trim();
  const priceNum = priceRaw ? parseFloat(priceRaw.replace(/[^0-9.]/g, "")) : null;
  const discount = discountRaw ? Math.max(0, Math.min(100, parseInt(discountRaw, 10) || 0)) : null;
  return {
    price: priceNum != null && !isNaN(priceNum) ? `$${priceNum.toFixed(2)}` : null,
    priceNumeric: priceNum != null && !isNaN(priceNum) ? priceNum : null,
    discount_percent: discount,
    store_url: url || null,
  };
}

function applyWishlistMeta(game) {
  const w = readWishlistFields();
  game.wishlist = true;
  game.wishlist_added = new Date().toISOString();
  if (w.price) game.price = w.price;
  if (w.discount_percent != null) game.discount_percent = w.discount_percent;
  if (w.store_url) game.store_url = w.store_url;
}

async function importSteamMatch(title, platform, match) {
  const status = document.getElementById("addGameStatus");
  const doImport = async () => {
  status.textContent = "Pulling details from Steam...";
  const reviews = await steamAppReviews(match.id) || {};
  const isWishlist = addGameTarget === "wishlist";
  const game = {
    store: isWishlist ? "wishlist" : platform,
    wishlist_store: isWishlist ? platform : undefined,
    id: (isWishlist ? "wish-" : "") + (platform === "steam" ? match.id : manualSlug(title || match.name)),
    name: title || match.name,
    header_image: match.tiny_image || `https://cdn.akamai.steamstatic.com/steam/apps/${match.id}/header.jpg`,
    library_image: `https://cdn.akamai.steamstatic.com/steam/apps/${match.id}/library_600x900_2x.jpg`,
    playtime_minutes: 0,
    last_played: null,
    release_date: null,
    genres: [],
    tags: [],
    steam_review_percent: reviews.steam_review_percent ?? null,
    steam_review_count: reviews.steam_review_count ?? null,
    steam_review_desc: reviews.steam_review_desc ?? null,
    hltb_main_hours: null,
    hltb_main_extra_hours: null,
    hltb_completionist_hours: null,
    hltb_match_confidence: null,
    hltb_name: null,
    store_url: `https://store.steampowered.com/app/${match.id}/`,
    steam_appid: match.id,
    steam_match_name: match.name,
    manual: true,
    added_at: new Date().toISOString(),
  };
  if (isWishlist) applyWishlistMeta(game);
  addManualGame(game);
  const where = isWishlist ? `wishlist (${platform})` : platform;
  status.textContent = `Saved "${game.name}" under ${where}.`;
  refreshAfterManualChange();
  setTimeout(closeAddGameModal, 700);
  };
  const name = title || match.name;
  runWithDuplicateCheck(name, doImport);
}

function importTitleOnly() {
  const title = document.getElementById("addGameTitle").value.trim();
  const platform = document.getElementById("addGamePlatform").value;
  if (!title) { document.getElementById("addGameStatus").textContent = "Enter a title first."; return; }
  const doImport = () => {
  const isWishlist = addGameTarget === "wishlist";
  const game = {
    store: isWishlist ? "wishlist" : platform,
    wishlist_store: isWishlist ? platform : undefined,
    id: (isWishlist ? "wish-" : "") + manualSlug(title),
    name: title,
    header_image: null,
    library_image: null,
    playtime_minutes: 0,
    last_played: null,
    release_date: null,
    genres: [],
    tags: [],
    steam_review_percent: null,
    steam_review_count: null,
    steam_review_desc: null,
    hltb_main_hours: null,
    hltb_main_extra_hours: null,
    hltb_completionist_hours: null,
    hltb_match_confidence: null,
    hltb_name: null,
    store_url: null,
    manual: true,
    added_at: new Date().toISOString(),
  };
  if (isWishlist) applyWishlistMeta(game);
  addManualGame(game);
  const where = isWishlist ? `wishlist (${platform})` : platform;
  document.getElementById("addGameStatus").textContent = `Saved "${title}" under ${where} (no Steam data).`;
  refreshAfterManualChange();
  setTimeout(closeAddGameModal, 700);
  };
  runWithDuplicateCheck(title, doImport);
}

export function bindAddGameModal() {
  const titleEl = document.getElementById("addGameTitle");
  const platformEl = document.getElementById("addGamePlatform");
  const searchBtn = document.getElementById("addGameSearch");
  const resultsEl = document.getElementById("addGameResults");
  const statusEl = document.getElementById("addGameStatus");

  document.getElementById("addGameBtn").addEventListener("click", openAddGameModal);
  document.getElementById("addGameClose").addEventListener("click", closeAddGameModal);
  document.querySelectorAll(".add-target-btn").forEach(btn => {
    btn.addEventListener("click", () => setAddGameTarget(btn.dataset.target));
  });
  document.getElementById("addGameModal").addEventListener("click", e => {
    if (e.target.id === "addGameModal") closeAddGameModal();
  });
  document.addEventListener("keydown", e => {
    if (e.key === "Escape" && !document.getElementById("addGameModal").classList.contains("hidden")) closeAddGameModal();
  });

  async function runSearch() {
    const term = titleEl.value.trim();
    if (!term) { statusEl.textContent = "Enter a title first."; return; }
    statusEl.textContent = "Searching Steam...";
    resultsEl.innerHTML = "";
    try {
      const matches = await steamSearch(term);
      if (!matches.length) {
        statusEl.textContent = "No Steam matches. Save without a match to add the title only.";
        return;
      }
      statusEl.textContent = `Pick a match to import:`;
      resultsEl.innerHTML = matches.map(m => `
        <button class="add-game-match w-full text-left flex gap-3 items-center bg-slate-700 hover:bg-slate-600 rounded p-2" data-appid="${m.id}">
          <img src="${m.tiny_image || ''}" alt="" class="w-20 h-10 object-cover rounded bg-slate-800" onerror="this.style.visibility='hidden'" />
          <div class="flex-1 min-w-0">
            <div class="text-sm text-slate-100 truncate">${escapeHtml(m.name)}</div>
            <div class="text-xs text-slate-400">App ${m.id}${m.price ? ` · ${escapeHtml(m.price.final_formatted || '')}` : ""}</div>
          </div>
          <span class="text-xs text-emerald-400">Import &rarr;</span>
        </button>
      `).join("");
    } catch (err) {
      statusEl.textContent = `Steam search failed: ${err.message}. (Steam may rate-limit; try again.)`;
    }
  }

  searchBtn.addEventListener("click", runSearch);
  titleEl.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); runSearch(); } });
  resultsEl.addEventListener("click", async e => {
    const btn = e.target.closest(".add-game-match");
    if (!btn) return;
    const appid = +btn.dataset.appid;
    const match = (await steamSearch(titleEl.value.trim())).find(m => m.id === appid);
    if (!match) { statusEl.textContent = "Couldn't refetch match details."; return; }
    await importSteamMatch(titleEl.value.trim(), platformEl.value, match);
  });
  document.getElementById("addGameSkipSteam").addEventListener("click", importTitleOnly);

  document.getElementById("addGameDupCancel")?.addEventListener("click", hideDuplicateWarn);
  document.getElementById("addGameDupAnyway")?.addEventListener("click", () => {
    const fn = _pendingAdd;
    hideDuplicateWarn();
    _bypassFor = fn;
    if (fn) fn();
  });
  document.getElementById("addGameDupGo")?.addEventListener("click", () => {
    const title = titleEl.value.trim();
    const match = findDuplicateMatch(title, addGameTarget, { includeHidden: true });
    const key = duplicateMatchKey(match);
    hideDuplicateWarn();
    closeAddGameModal();
    if (match) setGameHidden(match, false, { silent: true });
    if (key) flashGameRow(key);
  });

  titleEl.addEventListener("input", () => { _bypassFor = null; });

  document.getElementById("addGameExport").addEventListener("click", () => {
    download("steam-backlog-manual-games.json", JSON.stringify(loadManualGames(), null, 2), "application/json");
  });
  document.getElementById("addGameImport").addEventListener("change", async e => {
    const file = e.target.files[0];
    if (!file) return;
    try {
      const incoming = JSON.parse(await file.text());
      if (!Array.isArray(incoming)) throw new Error("File must be an array of manual games.");
      const merged = [...loadManualGames()];
      for (const g of incoming) {
        const idx = merged.findIndex(m => m.store === g.store && m.id === g.id);
        if (idx >= 0) merged[idx] = g; else merged.push(g);
      }
      saveManualGames(merged);
      refreshAfterManualChange();
      statusEl.textContent = `Imported ${incoming.length} manual games.`;
    } catch (err) {
      statusEl.textContent = `Import failed: ${err.message}`;
    }
    e.target.value = "";
  });
}
