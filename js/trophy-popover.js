import { escapeHtml } from './dom-util.js';

const POP_ID = 'trophyPop';
const GAP = 6;
const VIEWPORT_PAD = 8;

let popEl = null;
let anchorEl = null;
let pinned = false;
let hoverAnchor = null;
let escRelease = null;

function ensurePop() {
  if (popEl?.isConnected) return popEl;
  popEl = document.createElement('div');
  popEl.id = POP_ID;
  popEl.className = 'trophy-pop';
  popEl.setAttribute('role', 'tooltip');
  popEl.hidden = true;
  document.body.appendChild(popEl);
  return popEl;
}

function parseNum(val) {
  if (val == null || val === '') return null;
  const n = Number(val);
  return Number.isFinite(n) ? n : null;
}

function buildPopHtml(pill) {
  const label = pill.dataset.label || 'Completion';
  const pct = parseNum(pill.dataset.pct) ?? 0;
  const gsCur = parseNum(pill.dataset.gsCur);
  const gsTotal = parseNum(pill.dataset.gsTotal);
  const clamped = Math.max(0, Math.min(100, pct));
  let gsHtml = '';
  if (gsCur != null || gsTotal != null) {
    const cur = gsCur ?? 0;
    const total = gsTotal ?? 0;
    const remain = gsTotal != null && gsCur != null ? Math.max(0, total - cur) : null;
    const remainBit = remain != null ? ` · ${remain.toLocaleString()} remaining` : '';
    gsHtml = `<p class="trophy-pop-gs">Gamerscore: <strong>${cur.toLocaleString()}</strong> / <strong>${total.toLocaleString()}</strong>${remainBit}</p>`;
  }
  return `<p class="trophy-pop-title">${escapeHtml(label)}</p>
    <p class="trophy-pop-pct">${clamped}%</p>
    <div class="trophy-pop-bar" aria-hidden="true"><span class="trophy-pop-fill" style="width:${clamped}%"></span></div>
    ${gsHtml}`;
}

function positionPop(pill) {
  const pop = ensurePop();
  pop.hidden = false;
  const rect = pill.getBoundingClientRect();
  const popRect = pop.getBoundingClientRect();
  let top = rect.top - popRect.height - GAP;
  if (top < VIEWPORT_PAD) {
    top = rect.bottom + GAP;
  }
  let left = rect.left + rect.width / 2 - popRect.width / 2;
  left = Math.max(VIEWPORT_PAD, Math.min(left, window.innerWidth - popRect.width - VIEWPORT_PAD));
  pop.style.top = `${top}px`;
  pop.style.left = `${left}px`;
}

function setExpanded(pill, open) {
  pill.setAttribute('aria-expanded', open ? 'true' : 'false');
}

function clearEscBinding() {
  escRelease?.();
  escRelease = null;
}

function hidePop({ clearPin = true } = {}) {
  if (!popEl) return;
  popEl.hidden = true;
  if (anchorEl) setExpanded(anchorEl, false);
  anchorEl = null;
  hoverAnchor = null;
  if (clearPin) pinned = false;
  clearEscBinding();
}

function showFor(pill, { pin = false } = {}) {
  if (!pill?.matches?.('[data-trophy-pop]')) return;
  const pop = ensurePop();
  pop.innerHTML = buildPopHtml(pill);
  anchorEl = pill;
  if (pin) {
    pinned = true;
    hoverAnchor = null;
  } else {
    hoverAnchor = pill;
  }
  setExpanded(pill, true);
  positionPop(pill);
  if (pin && !escRelease) {
    const onEsc = (ev) => {
      if (ev.key === 'Escape') {
        ev.preventDefault();
        hidePop();
      }
    };
    document.addEventListener('keydown', onEsc);
    escRelease = () => document.removeEventListener('keydown', onEsc);
  }
}

function isPill(el) {
  return el?.matches?.('[data-trophy-pop]');
}

function onDocumentClick(e) {
  if (!pinned || !popEl || popEl.hidden) return;
  const pill = e.target.closest('[data-trophy-pop]');
  if (pill === anchorEl || popEl.contains(e.target)) return;
  hidePop();
}

function onScrollOrResize() {
  if (!popEl || popEl.hidden || !anchorEl) return;
  if (pinned) positionPop(anchorEl);
  else hidePop({ clearPin: false });
}

export function initTrophyPopover() {
  if (document.documentElement.dataset.trophyPopInit) return;
  document.documentElement.dataset.trophyPopInit = '1';

  document.addEventListener('mouseover', (e) => {
    const pill = e.target.closest('[data-trophy-pop]');
    if (!pill) return;
    if (pinned && anchorEl !== pill) return;
    showFor(pill, { pin: false });
  });

  document.addEventListener('mouseout', (e) => {
    if (pinned) return;
    const from = e.target.closest('[data-trophy-pop]');
    if (!from || from !== hoverAnchor) return;
    const to = e.relatedTarget;
    if (to && (from.contains(to) || popEl?.contains(to))) return;
    hidePop({ clearPin: false });
  });

  document.addEventListener('focusin', (e) => {
    const pill = e.target.closest('[data-trophy-pop]');
    if (!pill) return;
    if (pinned && anchorEl !== pill) return;
    showFor(pill, { pin: false });
  });

  document.addEventListener('focusout', (e) => {
    if (pinned) return;
    const pill = e.target.closest('[data-trophy-pop]');
    if (!pill || pill !== hoverAnchor) return;
    const to = e.relatedTarget;
    if (to && (pill.contains(to) || popEl?.contains(to))) return;
    hidePop({ clearPin: false });
  });

  document.addEventListener('click', (e) => {
    const pill = e.target.closest('[data-trophy-pop]');
    if (!pill) {
      onDocumentClick(e);
      return;
    }
    e.stopPropagation();
    e.preventDefault();
    if (pinned && anchorEl === pill) {
      hidePop();
      return;
    }
    showFor(pill, { pin: true });
  });

  document.addEventListener('click', onDocumentClick, true);

  window.addEventListener('scroll', onScrollOrResize, true);
  window.addEventListener('resize', onScrollOrResize);
}
