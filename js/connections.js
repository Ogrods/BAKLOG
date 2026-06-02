import { escapeAttr, escapeHtml } from './dom-util.js';



let authStatus = [];

let reconnectProviders = new Set();

let pollTimer = null;

let gridWired = false;

let chromeWired = false;

let _selectedKey = 'steam';



const STATUS_LABEL = {

  connected: 'Connected',

  unverified: 'Unverified',

  disconnected: 'Not connected',

  expired: 'Session expired',

};



const STATUS_CLASS = {

  connected: 'conn-pill conn-pill--ok',

  unverified: 'conn-pill conn-pill--unverified',

  disconnected: 'conn-pill conn-pill--off',

  expired: 'conn-pill conn-pill--warn',

};



const STATUS_NOTE = {

  unverified: 'Found in .env but never verified. Click Verify to sign in.',

  expired: 'Last fetcher run reported an auth failure. Reconnect to refresh.',

};



const PROVIDER_BRAND = {

  steam: { color: '#1b9cd8', initial: 'S' },

  gog: { color: '#a855f7', initial: 'G' },

  psn: { color: '#0070d1', initial: 'P' },

  epic: { color: '#888888', initial: 'E' },

  epic_wishlist: { color: '#888888', initial: 'E' },

  amazon: { color: '#ff9900', initial: 'A' },

  xbox: { color: '#107c10', initial: 'X' },

  xbox_wishlist: { color: '#107c10', initial: 'X' },

  battlenet: { color: '#148eff', initial: 'B' },

  nintendo: { color: '#e60012', initial: 'N' },

  ubisoft: { color: '#0072ff', initial: 'U' },

  itch: { color: '#fa5c5c', initial: 'I' },

  itad: { color: '#22d3ee', initial: 'I' },

};



function providerBrand(p) {

  const brand = PROVIDER_BRAND[p.key];

  if (brand) return brand;

  return {

    color: '#475569',

    initial: (p.label || '?').charAt(0).toUpperCase(),

  };

}



function primaryLabel(st) {

  if (st === 'connected' || st === 'expired') return 'Reconnect';

  if (st === 'unverified') return 'Verify';

  return 'Connect';

}



/** Rail order after Steam (friction + paired library/wishlist). */
const RAIL_ORDER = [
  'gog',
  'psn',
  'xbox',
  'xbox_wishlist',
  'epic_wishlist',
  'epic',
  'battlenet',
  'ubisoft',
  'nintendo',
  'itch',
  'itad',
  'amazon',
];

function railSortIndex(key) {
  const idx = RAIL_ORDER.indexOf(key);
  return idx >= 0 ? idx : RAIL_ORDER.length;
}

function orderedProviders() {
  const steam = authStatus.find(p => p.key === 'steam');
  const rest = authStatus
    .filter(p => p.key !== 'steam')
    .slice()
    .sort((a, b) => {
      const d = railSortIndex(a.key) - railSortIndex(b.key);
      if (d !== 0) return d;
      return (a.label || a.key).localeCompare(b.label || b.key);
    });
  return [...(steam ? [steam] : []), ...rest];
}



function ensureSelectedKey() {

  if (authStatus.some(p => p.key === _selectedKey)) return;

  const steam = authStatus.find(p => p.key === 'steam');

  _selectedKey = steam?.key || authStatus[0]?.key || 'steam';

}



function renderHero() {

  const countEl = document.getElementById('connHeroCount');

  const fillEl = document.getElementById('connProgressFill');

  if (!countEl || !fillEl) return;

  if (!authStatus.length) {

    countEl.textContent = 'Loading connections…';

    fillEl.style.width = '0%';

    return;

  }

  const connected = authStatus.filter(p => p.status === 'connected').length;

  const total = authStatus.length;

  countEl.textContent = `${connected} of ${total} connections made`;

  fillEl.style.width = total ? `${(connected / total) * 100}%` : '0%';

}



function buildFormFields(p) {

  return (p.form_fields || []).map(f => `

    <label>${escapeHtml(f.label)}

      <input type="${f.secret ? 'password' : 'text'}" data-field="${escapeAttr(f.key)}" placeholder="${escapeAttr(f.placeholder || '')}" autocomplete="off" />

    </label>`).join('');

}



function buildFormPanel(p) {

  return `

    <div class="conn-paste-panel">

      ${buildFormFields(p)}

      <div class="conn-paste-actions">

        <button type="button" class="conn-paste-clip" data-paste-clipboard>Paste</button>

        <button type="button" class="conn-save-btn conn-save" data-provider="${escapeAttr(p.key)}">Save key</button>

      </div>

    </div>`;

}



function buildCardFooter(p, st) {

  if (p.kind === 'local') {

    return `

      <div class="conn-card-footer">

        <span class="conn-local-label">Auto-detected from Amazon Games launcher</span>

      </div>`;

  }



  if (p.kind === 'manual') {

    return `

      <div class="conn-card-footer">

        <button type="button" class="conn-open-url" data-open-url data-provider="${escapeAttr(p.key)}">Open sign-in page</button>

      </div>`;

  }



  const label = primaryLabel(st);

  return `

    <div class="conn-card-footer">

      <button type="button" class="conn-primary" data-primary="browser" data-provider="${escapeAttr(p.key)}">${label}</button>

    </div>`;

}



async function pasteFromClipboard(card) {

  const log = card?.querySelector('.conn-log');

  const input = card?.querySelector('.conn-paste-panel [data-field]');

  if (!input) return;

  try {

    const text = await navigator.clipboard.readText();

    input.value = (text || '').trim();

    if (log) {

      log.classList.remove('hidden');

      log.textContent = 'Pasted from clipboard.';

    }

  } catch {

    if (log) {

      log.classList.remove('hidden');

      log.textContent = 'Could not read clipboard — paste into the field manually (Ctrl+V).';

    }

  }

}



function buildCardHtml(p) {

  const st = p.status || 'disconnected';

  const brand = providerBrand(p);

  const expiry = p.expiry_days ? `<p class="conn-meta">Typical session ~${p.expiry_days}d</p>` : '';

  const note = STATUS_NOTE[st] ? `<p class="conn-note">${escapeHtml(STATUS_NOTE[st])}</p>` : '';

  const err = p.last_error ? `<p class="conn-error">${escapeHtml(p.last_error)}</p>` : '';

  const hasFormFields = (p.form_fields || []).length > 0;

  const showFormPanel = hasFormFields && (p.kind === 'form' || p.kind === 'manual' || p.kind === 'browser');

  const showDisconnect = st !== 'disconnected' && p.kind !== 'local';



  return `

    <article class="conn-card${p.kind === 'manual' ? ' conn-card--manual' : ''}" data-provider="${escapeAttr(p.key)}">

      <div class="conn-card-stripe" style="background:${escapeAttr(brand.color)}"></div>

      <div class="conn-card-head">

        <div class="conn-brand-badge" style="background:${escapeAttr(brand.color)}">${escapeHtml(brand.initial)}</div>

        <div class="conn-head-actions">

          <span class="${STATUS_CLASS[st] || STATUS_CLASS.disconnected}">${STATUS_LABEL[st] || st}</span>

          ${showDisconnect ? `<button type="button" class="conn-disconnect-x" data-disconnect-quick data-provider="${escapeAttr(p.key)}" aria-label="Disconnect ${escapeAttr(p.label)}">&times;</button>` : ''}

        </div>

      </div>

      <div class="conn-card-body">

        <h3>${escapeHtml(p.label)}</h3>

        <p class="conn-desc">${escapeHtml(p.description || '')}</p>

        ${note}

        ${err}

        ${expiry}

        <p class="conn-log hidden" aria-live="polite"></p>

      </div>

      ${showFormPanel ? buildFormPanel(p) : ''}

      ${buildCardFooter(p, st)}

    </article>`;

}



function buildRailItemHtml(p, selected) {

  const st = p.status || 'disconnected';

  const brand = providerBrand(p);

  const sel = selected ? ' is-selected' : '';

  return `

    <div class="conn-rail-item${sel}" data-provider="${escapeAttr(p.key)}" role="option" tabindex="${selected ? '0' : '-1'}" aria-selected="${selected ? 'true' : 'false'}">

      <span class="conn-row-dot conn-row-dot--${escapeAttr(st)}" aria-hidden="true"></span>

      <span class="conn-row-badge" style="background:${escapeAttr(brand.color)}">${escapeHtml(brand.initial)}</span>

      <span class="conn-row-label">${escapeHtml(p.label)}</span>

      <span class="${STATUS_CLASS[st] || STATUS_CLASS.disconnected} conn-row-pill">${STATUS_LABEL[st] || st}</span>

    </div>`;

}



function buildSteamRailBlock(p, selected) {

  return `

    <div class="conn-rail-steam-wrap">

      <span class="conn-rail-eyebrow">Recommended first</span>

      ${buildRailItemHtml(p, selected)}

    </div>`;

}



function renderConnections() {

  const rail = document.getElementById('connRail');

  const pane = document.getElementById('connPane');

  if (!rail || !pane) return;

  renderHero();

  if (!authStatus.length) {

    rail.innerHTML = '';

    pane.innerHTML = '<p class="text-sm text-slate-400">Loading connections…</p>';

    return;

  }

  ensureSelectedKey();

  const ordered = orderedProviders();
  const railParts = [];
  const steam = ordered.find(p => p.key === 'steam');
  if (steam) {
    railParts.push(buildSteamRailBlock(steam, _selectedKey === steam.key));
  }
  for (const p of ordered) {
    if (p.key === 'steam') continue;
    railParts.push(buildRailItemHtml(p, _selectedKey === p.key));
  }

  rail.innerHTML = railParts.join('');

  const selected = authStatus.find(p => p.key === _selectedKey);

  pane.innerHTML = selected

    ? buildCardHtml(selected)

    : '<p class="text-sm text-slate-400">Select a provider on the left to get started.</p>';

}



function handleLayoutClick(ev) {

  const target = ev.target;

  const card = target.closest('.conn-card');

  const railItem = target.closest('.conn-rail-item');

  const provider = card?.dataset.provider || railItem?.dataset.provider;



  const disconnectBtn = target.closest('[data-disconnect-quick]');

  if (disconnectBtn && provider) {

    disconnectProvider(provider);

    return;

  }



  const pasteBtn = target.closest('[data-paste-clipboard]');

  if (pasteBtn && card) {

    pasteFromClipboard(card);

    return;

  }



  const openUrlBtn = target.closest('[data-open-url]');

  if (openUrlBtn && provider) {

    openManualUrl(provider);

    return;

  }



  const primaryBtn = target.closest('.conn-primary');

  if (primaryBtn?.dataset.provider) {

    startBrowserConnect(primaryBtn.dataset.provider);

    return;

  }



  const saveBtn = target.closest('.conn-save');

  if (saveBtn?.dataset.provider) {

    saveFormCredentials(saveBtn.dataset.provider);

    return;

  }



  if (railItem?.dataset.provider && !card) {

    _selectedKey = railItem.dataset.provider;

    renderConnections();

  }

}



function handleLayoutKeydown(ev) {

  const railItem = ev.target.closest('.conn-rail-item');

  if (!railItem || !authStatus.length) return;



  const order = orderedProviders().map(p => p.key);

  let idx = order.indexOf(_selectedKey);

  if (idx < 0) idx = 0;



  if (ev.key === 'ArrowDown') {

    ev.preventDefault();

    idx = Math.min(idx + 1, order.length - 1);

  } else if (ev.key === 'ArrowUp') {

    ev.preventDefault();

    idx = Math.max(idx - 1, 0);

  } else if (ev.key === 'Home') {

    ev.preventDefault();

    idx = 0;

  } else if (ev.key === 'End') {

    ev.preventDefault();

    idx = order.length - 1;

  } else if (ev.key === 'Enter' || ev.key === ' ') {

    if (ev.target.closest('button, input, select, a')) return;

    ev.preventDefault();

    _selectedKey = railItem.dataset.provider || _selectedKey;

    renderConnections();

    return;

  } else {

    return;

  }



  _selectedKey = order[idx];

  renderConnections();

  document.querySelector(`.conn-rail-item[data-provider="${_selectedKey}"]`)?.focus();

}



function wireGridEvents() {

  if (gridWired) return;

  const layout = document.getElementById('connLayout');

  if (!layout) return;

  layout.addEventListener('click', handleLayoutClick);

  layout.addEventListener('keydown', handleLayoutKeydown);

  gridWired = true;

}



function closeConnPopover() {

  const pop = document.getElementById('connPopover');

  const bd = document.getElementById('connPopoverBackdrop');

  const body = document.getElementById('connPopoverBody');

  if (pop) pop.hidden = true;

  if (bd) bd.hidden = true;

  if (body) body.innerHTML = '';

}



function openConnPopover(which) {

  const pop = document.getElementById('connPopover');

  const bd = document.getElementById('connPopoverBackdrop');

  const body = document.getElementById('connPopoverBody');

  if (!pop || !bd || !body) return;

  const tplId = which === 'howto' ? 'tplConnHowToPopover' : 'tplConnPassphrasePopover';

  const tpl = document.getElementById(tplId);

  if (!tpl) return;

  body.innerHTML = '';

  body.appendChild(tpl.content.cloneNode(true));

  bd.hidden = false;

  pop.hidden = false;

  if (which === 'passphrase') wireMasterPasswordSave();

}



function toggleKebabMenu(force) {

  const btn = document.getElementById('connKebabBtn');

  const menu = document.getElementById('connKebabMenu');

  if (!btn || !menu) return;

  const open = typeof force === 'boolean' ? force : menu.hidden;

  menu.hidden = !open;

  btn.setAttribute('aria-expanded', open ? 'true' : 'false');

}



function wireMasterPasswordSave() {

  const btn = document.getElementById('masterPasswordSave');

  if (!btn || btn.dataset.bound === '1') return;

  btn.dataset.bound = '1';

  btn.addEventListener('click', async () => {

    const pw = document.getElementById('masterPasswordInput')?.value || '';

    await fetch('/api/auth/master-password', {

      method: 'POST',

      headers: { 'Content-Type': 'application/json' },

      body: JSON.stringify({ password: pw || null }),

    });

    const hint = document.getElementById('masterPasswordHint');

    if (hint) hint.textContent = pw ? 'Master password set (portable encryption).' : 'Using OS keychain.';

  });

}



function wireChromeEvents() {

  if (chromeWired) return;

  const section = document.getElementById('connectionsContainer');

  if (!section) return;

  chromeWired = true;

  section.addEventListener('click', ev => {

    const target = ev.target;

    if (target.closest('#connKebabBtn')) {

      toggleKebabMenu();

      return;

    }

    const openTrigger = target.closest('[data-conn-open]');

    if (openTrigger) {

      toggleKebabMenu(false);

      openConnPopover(openTrigger.dataset.connOpen);

      return;

    }

    if (target.closest('[data-conn-close]') || target.closest('#connPopoverBackdrop')) {

      closeConnPopover();

      return;

    }

    if (!target.closest('#connKebabMenu')) {

      toggleKebabMenu(false);

    }

  });

  document.addEventListener('keydown', ev => {

    if (ev.key !== 'Escape') return;

    closeConnPopover();

    toggleKebabMenu(false);

  });

}





export function showReconnectBanner(providers) {

  for (const p of providers || []) reconnectProviders.add(p);

  renderReconnectBanner();

}



function renderReconnectBanner() {

  const el = document.getElementById('authReconnectBanner');

  if (!el) return;

  if (!reconnectProviders.size) {

    el.classList.add('hidden');

    el.innerHTML = '';

    return;

  }

  const names = [...reconnectProviders]

    .map(k => authStatus.find(p => p.key === k)?.label || k)

    .join(', ');

  el.classList.remove('hidden');

  el.innerHTML = `

    <span>Session expired for <strong>${escapeHtml(names)}</strong>.</span>

    <button type="button" class="underline ml-2" data-jump-connections>Reconnect in Connections</button>

    <button type="button" class="ml-2 opacity-70" data-dismiss-auth-banner aria-label="Dismiss">&times;</button>

  `;

  el.querySelector('[data-jump-connections]')?.addEventListener('click', () => {

    const first = reconnectProviders.values().next().value;

    if (first) _selectedKey = first;

    document.querySelector('.view-tab[data-view="connections"]')?.click();

    renderConnections();

  });

  el.querySelector('[data-dismiss-auth-banner]')?.addEventListener('click', () => {

    reconnectProviders.clear();

    renderReconnectBanner();

  });

}



async function fetchAuthStatus() {

  const res = await fetch('/api/auth/status');

  if (!res.ok) throw new Error(`auth status ${res.status}`);

  const data = await res.json();

  authStatus = data.providers || [];

  return authStatus;

}



async function openManualUrl(provider) {

  const card = document.querySelector(`.conn-card[data-provider="${provider}"]`);

  const log = card?.querySelector('.conn-log');

  if (log) {

    log.classList.remove('hidden');

    log.textContent = 'Opening in your default browser…';

  }

  const res = await fetch(`/api/auth/${provider}/open-url`, { method: 'POST' });

  const data = await res.json().catch(() => ({}));

  if (!res.ok) {

    if (log) log.textContent = data.error || `Could not open browser (${res.status})`;

    return;

  }

  if (log) log.textContent = 'Copy your API key from the browser tab, paste above, then Save key.';

}



async function saveFormCredentials(provider) {

  const card = document.querySelector(`.conn-card[data-provider="${provider}"]`);

  const log = card?.querySelector('.conn-log');

  const fields = {};

  card?.querySelectorAll('[data-field]').forEach(inp => {

    fields[inp.dataset.field] = inp.value;

  });

  if (log) {

    log.classList.remove('hidden');

    log.textContent = 'Saving…';

  }

  const res = await fetch(`/api/auth/${provider}/credentials`, {

    method: 'PUT',

    headers: { 'Content-Type': 'application/json' },

    body: JSON.stringify({ fields }),

  });

  const data = await res.json().catch(() => ({}));

  if (!res.ok) {

    if (log) log.textContent = data.error || `Save failed (${res.status})`;

    return;

  }

  if (log) log.textContent = 'Saved.';

  await refreshConnections();

}



async function disconnectProvider(provider) {

  await fetch(`/api/auth/${provider}/disconnect`, { method: 'POST' });

  reconnectProviders.delete(provider);

  renderReconnectBanner();

  await refreshConnections();

}



async function startBrowserConnect(provider) {

  const card = document.querySelector(`.conn-card[data-provider="${provider}"]`);

  const log = card?.querySelector('.conn-log');

  if (log) {

    log.classList.remove('hidden');

    log.textContent = 'Opening sign-in window…';

  }

  const res = await fetch(`/api/auth/${provider}/start`, { method: 'POST' });

  const data = await res.json().catch(() => ({}));

  if (!res.ok) {

    if (log) log.textContent = data.error || `Start failed (${res.status})`;

    return;

  }

  const es = new EventSource(`/api/auth/${data.session_id}/stream`);

  es.addEventListener('waiting_for_user', ev => {

    const msg = JSON.parse(ev.data);

    if (log) log.textContent = msg.message || 'Complete sign-in in the browser window…';

  });

  es.addEventListener('signed_in', () => {

    if (log) log.textContent = 'Signed in — extracting credentials…';

  });

  es.addEventListener('extracted', () => {

    if (log) log.textContent = 'Connected.';

    reconnectProviders.delete(provider);

    renderReconnectBanner();

    es.close();

    refreshConnections();

  });

  es.addEventListener('error', ev => {

    try {

      const msg = JSON.parse(ev.data);

      if (log) log.textContent = msg.message || 'Sign-in failed';

    } catch {

      if (log) log.textContent = 'Sign-in failed or window closed.';

    }

    es.close();

  });

  es.addEventListener('done', () => es.close());

}



export async function refreshConnections() {

  try {

    await fetchAuthStatus();

    renderConnections();

    renderReconnectBanner();

  } catch {

    const rail = document.getElementById('connRail');

    const pane = document.getElementById('connPane');

    if (rail) rail.innerHTML = '';

    if (pane) {

      pane.innerHTML = '<p class="text-sm text-amber-400">Could not load connection status (is server.py running?).</p>';

    }

    renderHero();

  }

}



export function startConnectionsPolling() {

  stopConnectionsPolling();

  pollTimer = setInterval(() => {

    if (document.getElementById('connectionsContainer')?.classList.contains('hidden')) return;

    refreshConnections();

  }, 15000);

}



export function stopConnectionsPolling() {

  if (pollTimer) clearInterval(pollTimer);

  pollTimer = null;

}



export function wireConnectionsUi() {

  wireGridEvents();

  wireChromeEvents();

}



export function initConnections() {

  wireConnectionsUi();

  refreshConnections();

}



/** Map fetcher chip key -> auth provider for reconnect hints. */

export const FETCHER_AUTH_PROVIDER = {

  steam: 'steam',

  gog: 'gog',

  psn: 'psn',

  epic: 'epic',

  amazon: 'amazon',

  xbox: 'xbox',

  battlenet: 'battlenet',

  ubisoft: 'ubisoft',

  nintendo: 'nintendo',

  itch: 'itch',

  wishlistSteam: 'steam',

  wishlistGog: 'gog',

  wishlistEpic: 'epic_wishlist',

  wishlistPsn: 'psn',

  wishlistUbisoft: 'ubisoft',

  wishlistXbox: 'xbox_wishlist',

  itad: 'itad',

};



export function providerForFetcher(key) {

  return FETCHER_AUTH_PROVIDER[key] || null;

}



export function noteFetcherAuthFailure(fetcherKey, logText) {

  const provider = providerForFetcher(fetcherKey);

  if (!provider) return;

  const authish = /401|403|auth|cookie|session|credential|sign in|npsso|rejected/i.test(logText || '');

  if (authish) showReconnectBanner([provider]);

}

