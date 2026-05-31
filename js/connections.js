import { escapeAttr, escapeHtml } from './dom-util.js';

let authStatus = [];
let reconnectProviders = new Set();
let pollTimer = null;
let gridWired = false;

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

function closeAllMenus() {
  document.querySelectorAll('.conn-menu:not(.hidden)').forEach(menu => {
    menu.classList.add('hidden');
  });
}

function closeSettingsPopover() {
  const pop = document.getElementById('connSettingsPopover');
  const btn = document.getElementById('connSettingsBtn');
  pop?.classList.add('hidden');
  if (btn) btn.setAttribute('aria-expanded', 'false');
}

function togglePastePanel(card) {
  const panel = card?.querySelector('.conn-paste-panel');
  if (panel) panel.classList.toggle('hidden');
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
  countEl.textContent = `${connected} of ${total} stores connected`;
  fillEl.style.width = total ? `${(connected / total) * 100}%` : '0%';
}

function buildFormFields(p) {
  return (p.form_fields || []).map(f => `
    <label>${escapeHtml(f.label)}
      <input type="${f.secret ? 'password' : 'text'}" data-field="${escapeAttr(f.key)}" placeholder="${escapeAttr(f.placeholder || '')}" autocomplete="off" />
    </label>`).join('');
}

function buildMenuItems(p, st) {
  const items = [];
  if (st !== 'disconnected') {
    items.push('<button type="button" data-action="disconnect">Disconnect</button>');
  }
  if ((p.form_fields || []).length) {
    items.push('<button type="button" data-action="paste-key">Paste API key</button>');
  }
  if (p.kind === 'manual') {
    items.push('<button type="button" data-action="open-url">Open sign-in page</button>');
  }
  return items.join('');
}

function buildCardFooter(p, st) {
  const showLocal = p.kind === 'local';
  const showBrowser = p.kind === 'browser' || p.kind === 'oauth';
  const showForm = p.kind === 'form';
  const showManual = p.kind === 'manual';
  const menuItems = buildMenuItems(p, st);
  const hasMenu = menuItems.length > 0;

  if (showLocal) {
    return `
      <div class="conn-card-footer">
        <span class="conn-local-label">Auto-detected from Amazon Games launcher</span>
        ${hasMenu ? `<button type="button" class="conn-overflow" aria-label="More" data-open-menu>&#8943;</button>
        <div class="conn-menu hidden" role="menu">${menuItems}</div>` : ''}
      </div>`;
  }

  const label = primaryLabel(st);
  const primaryAction = (showBrowser || p.kind === 'oauth')
    ? 'browser'
    : (showForm || showManual ? 'paste' : 'browser');

  return `
    <div class="conn-card-footer">
      <button type="button" class="conn-primary" data-primary="${primaryAction}" data-provider="${escapeAttr(p.key)}">${label}</button>
      ${hasMenu ? `<button type="button" class="conn-overflow" aria-label="More" data-open-menu>&#8943;</button>
      <div class="conn-menu hidden" role="menu">${menuItems}</div>` : ''}
    </div>`;
}

function renderConnections() {
  const grid = document.getElementById('connectionsGrid');
  if (!grid) return;
  renderHero();
  if (!authStatus.length) {
    grid.innerHTML = '<p class="text-sm text-slate-400">Loading connections…</p>';
    return;
  }
  grid.innerHTML = authStatus.map(p => {
    const st = p.status || 'disconnected';
    const brand = providerBrand(p);
    const expiry = p.expiry_days ? `<p class="conn-meta">Typical session ~${p.expiry_days}d</p>` : '';
    const note = STATUS_NOTE[st] ? `<p class="conn-note">${escapeHtml(STATUS_NOTE[st])}</p>` : '';
    const err = p.last_error ? `<p class="conn-error">${escapeHtml(p.last_error)}</p>` : '';
    const hasFormFields = (p.form_fields || []).length > 0;
    const showFormPanel = hasFormFields && (p.kind === 'form' || p.kind === 'manual' || p.kind === 'browser');

    return `
      <article class="conn-card" data-provider="${escapeAttr(p.key)}">
        <div class="conn-card-stripe" style="background:${escapeAttr(brand.color)}"></div>
        <div class="conn-card-head">
          <div class="conn-brand-badge" style="background:${escapeAttr(brand.color)}">${escapeHtml(brand.initial)}</div>
          <span class="${STATUS_CLASS[st] || STATUS_CLASS.disconnected}">${STATUS_LABEL[st] || st}</span>
        </div>
        <div class="conn-card-body">
          <h3>${escapeHtml(p.label)}</h3>
          <p class="conn-desc">${escapeHtml(p.description || '')}</p>
          ${note}
          ${err}
          ${expiry}
          <p class="conn-log hidden" aria-live="polite"></p>
        </div>
        ${buildCardFooter(p, st)}
        ${showFormPanel ? `
          <div class="conn-paste-panel hidden">
            ${buildFormFields(p)}
            <button type="button" class="conn-save-btn conn-save" data-provider="${escapeAttr(p.key)}">Save key</button>
          </div>` : ''}
      </article>`;
  }).join('');
}

function handleGridClick(ev) {
  const target = ev.target;

  const openBtn = target.closest('[data-open-menu]');
  if (openBtn) {
    ev.stopPropagation();
    const footer = openBtn.closest('.conn-card-footer');
    const menu = footer?.querySelector('.conn-menu');
    if (!menu) return;
    const wasOpen = !menu.classList.contains('hidden');
    closeAllMenus();
    if (!wasOpen) menu.classList.remove('hidden');
    return;
  }

  const actionBtn = target.closest('[data-action]');
  if (actionBtn) {
    ev.stopPropagation();
    const card = actionBtn.closest('.conn-card');
    const provider = card?.dataset.provider;
    if (!provider) return;
    const action = actionBtn.dataset.action;
    closeAllMenus();
    if (action === 'disconnect') disconnectProvider(provider);
    else if (action === 'paste-key') togglePastePanel(card);
    else if (action === 'open-url') openManualUrl(provider);
    return;
  }

  const primaryBtn = target.closest('.conn-primary');
  if (primaryBtn) {
    const provider = primaryBtn.dataset.provider;
    const card = primaryBtn.closest('.conn-card');
    const action = primaryBtn.dataset.primary;
    if (action === 'browser') startBrowserConnect(provider);
    else if (action === 'paste') togglePastePanel(card);
  }

  const saveBtn = target.closest('.conn-save');
  if (saveBtn) {
    saveFormCredentials(saveBtn.dataset.provider);
  }
}

function wireGridEvents() {
  if (gridWired) return;
  const grid = document.getElementById('connectionsGrid');
  if (!grid) return;
  grid.addEventListener('click', handleGridClick);
  gridWired = true;
}

function wireGlobalDismiss() {
  document.addEventListener('click', ev => {
    if (!ev.target.closest('.conn-card-footer') && !ev.target.closest('.conn-menu')) {
      closeAllMenus();
    }
    if (!ev.target.closest('#connSettingsPopover') && !ev.target.closest('#connSettingsBtn')) {
      closeSettingsPopover();
    }
  });
  document.addEventListener('keydown', ev => {
    if (ev.key === 'Escape') {
      closeAllMenus();
      closeSettingsPopover();
    }
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
    document.querySelector('.view-tab[data-view="connections"]')?.click();
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
  togglePastePanel(card);
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
    const grid = document.getElementById('connectionsGrid');
    if (grid) grid.innerHTML = '<p class="text-sm text-amber-400">Could not load connection status (is server.py running?).</p>';
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

export async function connectAllWizard() {
  const pending = authStatus.filter(p => p.status !== 'connected' && (p.kind === 'browser' || p.kind === 'oauth' || p.kind === 'form'));
  if (!pending.length) return;
  document.querySelector('.view-tab[data-view="connections"]')?.click();
  for (const p of pending) {
    // eslint-disable-next-line no-await-in-loop
    await new Promise(r => setTimeout(r, 300));
    if (p.kind === 'form') {
      // eslint-disable-next-line no-continue
      continue;
    }
    // eslint-disable-next-line no-await-in-loop
    await startBrowserConnect(p.key);
  }
}

export function wireConnectionsUi() {
  wireGridEvents();
  wireGlobalDismiss();
  document.getElementById('connectAllBtn')?.addEventListener('click', connectAllWizard);
  document.getElementById('connSettingsBtn')?.addEventListener('click', ev => {
    ev.stopPropagation();
    const pop = document.getElementById('connSettingsPopover');
    const btn = document.getElementById('connSettingsBtn');
    if (!pop || !btn) return;
    const open = pop.classList.contains('hidden');
    closeSettingsPopover();
    closeAllMenus();
    if (open) {
      pop.classList.remove('hidden');
      btn.setAttribute('aria-expanded', 'true');
    }
  });
  document.getElementById('masterPasswordSave')?.addEventListener('click', async () => {
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
