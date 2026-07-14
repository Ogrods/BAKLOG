import { escapeHtml } from "./dom-util.js";
import { isPro } from "./auth-gate.js";

const POP_ID = "trophyPop";
const DEEP_SYNC_STORES = new Set(["psn", "xbox"]);
const GAP = 6;
const VIEWPORT_PAD = 8;

let popEl = null;
let anchorEl = null;
let hoverAnchor = null;

function ensurePop() {
  if (popEl?.isConnected) return popEl;
  popEl = document.createElement("div");
  popEl.id = POP_ID;
  popEl.className = "trophy-pop";
  popEl.setAttribute("role", "tooltip");
  popEl.hidden = true;
  popEl.addEventListener("click", onDeepSyncClick);
  document.body.appendChild(popEl);
  return popEl;
}

function onDeepSyncClick(e) {
  const btn = e.target.closest("[data-deep-sync]");
  if (!btn) return;
  e.preventDefault();
  e.stopPropagation();
  if (btn.disabled) return;
  document.dispatchEvent(
    new CustomEvent("baklog:deep-sync", {
      detail: {
        store: btn.dataset.store,
        key: btn.dataset.key || null,
        name: btn.dataset.name || null,
      },
    }),
  );
}

function parseNum(val) {
  if (val == null || val === "") return null;
  const n = Number(val);
  return Number.isFinite(n) ? n : null;
}

function buildPopHtml(pill) {
  const label = pill.dataset.label || "Completion";
  const pct = parseNum(pill.dataset.pct) ?? 0;
  const gsCur = parseNum(pill.dataset.gsCur);
  const gsTotal = parseNum(pill.dataset.gsTotal);
  const troCur = parseNum(pill.dataset.troCur);
  const troTotal = parseNum(pill.dataset.troTotal);
  const store = (pill.dataset.store || "").toLowerCase();
  const clamped = Math.max(0, Math.min(100, pct));
  let gsHtml = "";
  if (store === "psn" && (troCur != null || troTotal != null)) {
    const cur = troCur ?? 0;
    const total = troTotal ?? 0;
    const remain =
      troTotal != null && troCur != null ? Math.max(0, total - cur) : null;
    const remainBit =
      remain != null ? ` · ${remain.toLocaleString()} remaining` : "";
    gsHtml = `<p class="trophy-pop-gs">Trophies: <strong>${cur.toLocaleString()}</strong> / <strong>${total.toLocaleString()}</strong>${remainBit}</p>`;
  } else if (gsCur != null || gsTotal != null) {
    const cur = gsCur ?? 0;
    const total = gsTotal ?? 0;
    const remain =
      gsTotal != null && gsCur != null ? Math.max(0, total - cur) : null;
    const remainBit =
      remain != null ? ` · ${remain.toLocaleString()} remaining` : "";
    gsHtml = `<p class="trophy-pop-gs">Gamerscore: <strong>${cur.toLocaleString()}</strong> / <strong>${total.toLocaleString()}</strong>${remainBit}</p>`;
  }
  return `<p class="trophy-pop-title">${escapeHtml(label)}</p>
    <p class="trophy-pop-pct">${clamped}%</p>
    <div class="trophy-pop-bar" aria-hidden="true"><span class="trophy-pop-fill" style="width:${clamped}%"></span></div>
    ${gsHtml}
    ${buildMeterHtml(pill)}`;
}

/** Pro-only deep-sync footer for PSN/Xbox pills: cached % is free; a full
 *  achievement/trophy re-pull is a paid-tier action. */
function buildMeterHtml(pill) {
  if (!isPro()) return "";
  const store = (pill.dataset.store || "").toLowerCase();
  if (!DEEP_SYNC_STORES.has(store)) return "";
  const key = pill.dataset.key || "";
  const name = pill.dataset.name || "";
  return `<div class="trophy-pop-meter">
    <button type="button" class="trophy-pop-sync" data-deep-sync data-store="${escapeHtml(store)}" data-key="${escapeHtml(key)}" data-name="${escapeHtml(name)}">Deep sync</button>
  </div>`;
}

function positionPop(pill) {
  const pop = ensurePop();
  pop.hidden = false;
  pop.classList.toggle(
    "trophy-pop--interactive",
    !!pop.querySelector("[data-deep-sync]"),
  );
  const rect = pill.getBoundingClientRect();
  const popRect = pop.getBoundingClientRect();
  let top = rect.top - popRect.height - GAP;
  if (top < VIEWPORT_PAD) {
    top = rect.bottom + GAP;
  }
  let left = rect.left + rect.width / 2 - popRect.width / 2;
  left = Math.max(
    VIEWPORT_PAD,
    Math.min(left, window.innerWidth - popRect.width - VIEWPORT_PAD),
  );
  pop.style.top = `${top}px`;
  pop.style.left = `${left}px`;
}

function setExpanded(pill, open) {
  pill.setAttribute("aria-expanded", open ? "true" : "false");
}

function hidePop() {
  if (!popEl) return;
  popEl.hidden = true;
  popEl.classList.remove("trophy-pop--interactive");
  if (anchorEl) setExpanded(anchorEl, false);
  anchorEl = null;
  hoverAnchor = null;
}

function showFor(pill) {
  if (!pill?.matches?.("[data-trophy-pop]")) return;
  const pop = ensurePop();
  pop.replaceChildren();
  pop.insertAdjacentHTML("beforeend", buildPopHtml(pill));
  anchorEl = pill;
  hoverAnchor = pill;
  setExpanded(pill, true);
  positionPop(pill);
}

function onScrollOrResize() {
  if (!popEl || popEl.hidden || !anchorEl) return;
  hidePop();
}

export function initTrophyPopover() {
  if (document.documentElement.dataset.trophyPopInit) return;
  document.documentElement.dataset.trophyPopInit = "1";

  document.addEventListener("mouseover", (e) => {
    const pill = e.target.closest("[data-trophy-pop]");
    if (!pill) return;
    showFor(pill);
  });

  document.addEventListener("mouseout", (e) => {
    const from = e.target.closest("[data-trophy-pop]");
    if (!from || from !== hoverAnchor) return;
    const to = e.relatedTarget;
    if (to && (from.contains(to) || popEl?.contains(to))) return;
    hidePop();
  });

  document.addEventListener("focusin", (e) => {
    const pill = e.target.closest("[data-trophy-pop]");
    if (!pill) return;
    showFor(pill);
  });

  document.addEventListener("focusout", (e) => {
    const pill = e.target.closest("[data-trophy-pop]");
    if (!pill || pill !== hoverAnchor) return;
    const to = e.relatedTarget;
    if (to && (pill.contains(to) || popEl?.contains(to))) return;
    hidePop();
  });

  window.addEventListener("scroll", onScrollOrResize, true);
  window.addEventListener("resize", onScrollOrResize);
}
