import { escapeAttr, escapeHtml } from './dom-util.js';
import { bindEscapeClose, trapFocus } from './focus-trap.js';
import { FETCHER_AUTH_PROVIDER } from './fetcher-registry.js';
import { state } from './state.js';

export { FETCHER_AUTH_PROVIDER };

let _connPopoverRelease = null;

let authStatus = [];

let _authStatusLoaded = false;

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

  unavailable: 'Unavailable',

};



const STATUS_CLASS = {

  connected: 'conn-pill conn-pill--ok',

  unverified: 'conn-pill conn-pill--unverified',

  disconnected: 'conn-pill conn-pill--off',

  expired: 'conn-pill conn-pill--warn',

  unavailable: 'conn-pill conn-pill--off',

};



const STATUS_NOTE = {

  unverified: 'Found in .env but never verified. Click Verify to sign in.',

  expired: 'Last fetcher run reported an auth failure. Reconnect to refresh.',

  unavailable: 'Not available on this operating system.',

};



const PROVIDER_BRAND = {

  steam: { color: '#1b9cd8', initial: 'S' },

  gog: { color: '#a855f7', initial: 'G' },

  psn: { color: '#0070d1', initial: 'P' },

  epic: { color: '#888888', initial: 'E' },

  epic_wishlist: { color: '#888888', initial: 'E' },

  amazon: { color: '#ff9900', initial: 'A' },
  amazon_web: { color: '#ff9900', initial: 'A' },

  xbox: { color: '#107c10', initial: 'X' },

  xbox_wishlist: { color: '#107c10', initial: 'X' },

  battlenet: { color: '#148eff', initial: 'B' },

  nintendo: { color: '#e60012', initial: 'N' },

  nintendo_wishlist: { color: '#e60012', initial: 'N' },

  ubisoft: { color: '#0072ff', initial: 'U' },

  humble: { color: '#cc2929', initial: 'H' },

  ea: { color: '#ff4747', initial: 'EA' },

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


const CONN_BADGE_LETTER = {
  steam: 'S',
  gog: 'G',
  psn: 'P',
  epic: 'E',
  amazon: 'A',
  xbox: 'X',
  battlenet: 'B',
  nintendo: 'N',
  ubisoft: 'U',
  humble: 'H',
  ea: 'EA',
  itch: 'I',
  itad: 'I',
};

function connBadge(p) {
  // Collapse store variants onto the base brand badge so they share the same
  // background/letter (e.g. amazon_web -> amazon, xbox_wishlist -> xbox).
  const cls = (p.key || '').replace(/_(wishlist|web)$/, '');
  return {
    cls,
    letter: CONN_BADGE_LETTER[cls] || (p.label || '?').charAt(0).toUpperCase(),
  };
}


function primaryLabel(st) {

  if (st === 'connected' || st === 'expired') return 'Reconnect';

  if (st === 'unverified') return 'Verify';

  return 'Connect';

}



/**
 * Rail order after Steam, sorted by ease of use (smoothest first), with each
 * company's library + wishlist kept adjacent and the library always first.
 * Tiers: smooth long-lived browser logins -> no-login / paste-once sources ->
 * short-lived or flaky logins (EA's ~1-day token is the most painful).
 */
const RAIL_ORDER = [
  'gog',
  'psn',
  'xbox',
  'xbox_wishlist',
  'humble',
  'epic',
  'epic_wishlist',
  'amazon',
  'amazon_web',
  'itch',
  'itad',
  'battlenet',
  'ubisoft',
  'nintendo',
  'nintendo_wishlist',
  'ea',
];

/** Collapsed rail entries: one button, multiple detail cards (web on top). */
const PROVIDER_GROUPS = {
  amazon: { label: 'Amazon', members: ['amazon_web', 'amazon'] },
};
const GROUP_OF = Object.fromEntries(
  Object.entries(PROVIDER_GROUPS).flatMap(([g, d]) => d.members.map(k => [k, g])),
);
const STATUS_RANK = { connected: 4, expired: 3, unverified: 2, disconnected: 1, unavailable: 0 };

export function groupRepFor(key) {
  return GROUP_OF[key] || key;
}

export function combinedGroupStatus(members) {
  return members.reduce((best, p) => {
    const st = p.status || 'disconnected';
    return (STATUS_RANK[st] ?? 0) > (STATUS_RANK[best] ?? 0) ? st : best;
  }, 'disconnected');
}

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

function railEntries() {
  const out = [];
  const seen = new Set();
  for (const p of orderedProviders()) {
    const g = GROUP_OF[p.key];
    if (!g) {
      out.push(p);
      continue;
    }
    if (seen.has(g)) continue;
    seen.add(g);
    const members = PROVIDER_GROUPS[g].members
      .map(k => authStatus.find(x => x.key === k))
      .filter(Boolean);
    out.push({
      key: g,
      label: PROVIDER_GROUPS[g].label,
      status: combinedGroupStatus(members),
      available: members.some(m => m.available !== false),
      _group: true,
    });
  }
  return out;
}

function ensureSelectedKey() {
  if (authStatus.some(p => p.key === _selectedKey)) return;
  const rep = groupRepFor(_selectedKey);
  if (
    PROVIDER_GROUPS[rep]
    && PROVIDER_GROUPS[rep].members.some(k => authStatus.some(p => p.key === k))
  ) {
    _selectedKey = rep;
    return;
  }
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

  const connected = connectedProviderCount();

  const total = authStatus.length;

  countEl.textContent = `${connected} of ${total} connections made`;

  fillEl.style.width = total ? `${(connected / total) * 100}%` : '0%';

}



function renderOnboard() {

  const el = document.getElementById('connOnboard');

  if (!el) return;

  if (!authStatus.length || connectedProviderCount() > 0) {

    el.innerHTML = '';

    el.hidden = true;

    return;

  }

  el.hidden = false;

  el.innerHTML = `

    <div class="conn-onboard" role="region" aria-label="Get started">

      <p class="conn-onboard-title">You have 0 stores connected</p>

      <p class="conn-onboard-lead">Start with Steam — it imports your whole library in one sign-in. You can add the rest after.</p>

      <button type="button" class="conn-onboard-btn" data-conn-start-steam>Start with Steam</button>

      <p class="conn-onboard-muted">or pick any store from the list below</p>

    </div>`;

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


/**
 * Browser providers connect via the primary button; their form field is only a
 * manual fallback. Fold it into a collapsed drawer so it doesn't look like a
 * required step.
 */
function buildFallbackPanel(p) {
  return `
    <details class="conn-fallback">
      <summary class="conn-fallback-summary">
        <span class="conn-fallback-chevron" aria-hidden="true">&rsaquo;</span>
        <span>Trouble connecting? Enter a code manually</span>
      </summary>
      <div class="conn-fallback-body">
        ${buildFormPanel(p)}
      </div>
    </details>`;
}


function disconnectBtnHtml(p, st) {
  const show = st !== 'disconnected' && st !== 'unverified' && p.kind !== 'local';
  return show
    ? `<button type="button" class="conn-disconnect" data-disconnect-quick data-provider="${escapeAttr(p.key)}">Disconnect</button>`
    : '';
}


function buildCardFooter(p, st) {

  if (p.available === false) {

    const plats = (p.platforms || []).join(', ') || 'Windows';

    return `

      <div class="conn-card-footer">

        <span class="conn-local-label">${escapeHtml(`Available on ${plats} only`)}</span>

      </div>`;

  }

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

        ${disconnectBtnHtml(p, st)}

      </div>`;

  }



  const label = primaryLabel(st);

  return `

    <div class="conn-card-footer">

      <button type="button" class="conn-primary" data-primary="browser" data-provider="${escapeAttr(p.key)}">${label}</button>

      ${disconnectBtnHtml(p, st)}

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
  const badge = connBadge(p);

  const expiry = p.expiry_days ? `<p class="conn-meta">Typical session ~${p.expiry_days}d</p>` : '';

  const note = STATUS_NOTE[st] ? `<p class="conn-note">${escapeHtml(STATUS_NOTE[st])}</p>` : '';

  const err = p.last_error ? `<p class="conn-error">${escapeHtml(p.last_error)}</p>` : '';

  const tips = (p.tips || []).length
    ? `<ul class="conn-tips">${p.tips.map(t => `<li>${escapeHtml(t)}</li>`).join('')}</ul>`
    : '';

  const hasFormFields = (p.form_fields || []).length > 0;

  const showFormPanel = hasFormFields && (p.kind === 'form' || p.kind === 'manual' || p.kind === 'browser');



  return `

    <article class="conn-card${p.kind === 'manual' ? ' conn-card--manual' : ''}" data-provider="${escapeAttr(p.key)}">

      <div class="conn-card-stripe" style="background:${escapeAttr(brand.color)}"></div>

      <div class="conn-card-head">

        <span class="store-badge store-badge--lg ${escapeAttr(badge.cls)}">${escapeHtml(badge.letter)}</span>

        <div class="conn-head-actions">

          <span class="${STATUS_CLASS[st] || STATUS_CLASS.disconnected}">${STATUS_LABEL[st] || st}</span>

        </div>

      </div>

      <div class="conn-card-body">

        <h3>${escapeHtml(p.label)}</h3>

        <p class="conn-desc">${escapeHtml(p.description || '')}</p>

        ${tips}

        ${note}

        ${err}

        ${expiry}

        <p class="conn-log hidden" aria-live="polite"></p>

      </div>

      ${showFormPanel ? (p.kind === 'browser' ? buildFallbackPanel(p) : buildFormPanel(p)) : ''}

      ${buildCardFooter(p, st)}

    </article>`;

}



function buildRailItemHtml(p, selected) {

  const st = p.status || 'disconnected';

  const badge = connBadge(p);

  const sel = selected ? ' is-selected' : '';

  const unavailable = p.available === false;

  const unav = unavailable ? ' is-unavailable' : '';

  const title = unavailable
    ? ` title="${escapeAttr(`${p.label} is available on ${(p.platforms || []).join(', ') || 'Windows'} only`)}"`
    : '';

  return `

    <div class="conn-rail-item${sel}${unav}" data-provider="${escapeAttr(p.key)}" role="option" tabindex="${selected ? '0' : '-1'}" aria-selected="${selected ? 'true' : 'false'}"${title}>

      <span class="conn-row-dot conn-row-dot--${escapeAttr(st)}" aria-hidden="true"></span>

      <span class="store-badge conn-rail-badge ${escapeAttr(badge.cls)}">${escapeHtml(badge.letter)}</span>

      <span class="conn-row-label">${escapeHtml(p.label)}</span>

      <span class="${STATUS_CLASS[st] || STATUS_CLASS.disconnected} conn-row-pill">${STATUS_LABEL[st] || st}</span>

    </div>`;

}



function buildSteamRailBlock(p, selected) {

  const caption = (p.status === 'connected')
    ? ''
    : '<span class="conn-rail-rec-caption">Recommended first</span>';

  return `

    <div class="conn-rail-steam-wrap">

      ${caption}

      ${buildRailItemHtml(p, selected)}

    </div>`;

}



function renderConnections() {

  const rail = document.getElementById('connRail');

  const pane = document.getElementById('connPane');

  if (!rail || !pane) return;

  renderHero();

  renderOnboard();

  if (!authStatus.length) {

    rail.innerHTML = '';

    pane.innerHTML = '<p class="text-sm text-slate-400">Loading connections…</p>';

    return;

  }

  ensureSelectedKey();

  const selKey = groupRepFor(_selectedKey);
  const entries = railEntries();
  const railParts = [];
  const steam = entries.find(e => e.key === 'steam');
  if (steam) {
    railParts.push(buildSteamRailBlock(steam, selKey === steam.key));
  }
  for (const entry of entries) {
    if (entry.key === 'steam') continue;
    railParts.push(buildRailItemHtml(entry, selKey === entry.key));
  }

  rail.innerHTML = railParts.join('');

  if (PROVIDER_GROUPS[selKey]) {
    const members = PROVIDER_GROUPS[selKey].members
      .map(k => authStatus.find(x => x.key === k))
      .filter(Boolean);
    pane.innerHTML = `<div class="conn-card-stack">${members.map(buildCardHtml).join('')}</div>`;
  } else {
    const selected = authStatus.find(p => p.key === selKey);
    pane.innerHTML = selected
      ? buildCardHtml(selected)
      : '<p class="text-sm text-slate-400">Select a provider on the left to get started.</p>';
  }

}



function handleLayoutClick(ev) {

  const target = ev.target;



  const startSteam = target.closest('[data-conn-start-steam]');

  if (startSteam) {

    ev.preventDefault();

    reconnectProvider('steam');

    return;

  }



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



  const order = railEntries().map(e => e.key);

  let idx = order.indexOf(groupRepFor(_selectedKey));

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

  const container = document.getElementById('connectionsContainer');

  const layout = document.getElementById('connLayout');

  if (!container || !layout) return;

  container.addEventListener('click', handleLayoutClick);

  layout.addEventListener('keydown', handleLayoutKeydown);

  gridWired = true;

}



function closeConnPopover() {

  _connPopoverRelease?.();
  _connPopoverRelease = null;

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

  const tplMap = {
    howto: 'tplConnHowToPopover',
    passphrase: 'tplConnPassphrasePopover',
    bundle: 'tplConnBundlePopover',
  };

  const tplId = tplMap[which] || 'tplConnHowToPopover';

  const tpl = document.getElementById(tplId);

  if (!tpl) return;

  body.innerHTML = '';

  body.appendChild(tpl.content.cloneNode(true));

  bd.hidden = false;

  pop.hidden = false;

  if (which === 'passphrase') wireMasterPasswordSave();
  if (which === 'bundle') wireSecretsBundle();

  const titleMap = {
    howto: 'How connections work',
    passphrase: 'Encryption passphrase',
    bundle: 'Portable bundle',
  };
  const dialogTitle = document.getElementById('connPopoverDialogTitle');
  if (dialogTitle) dialogTitle.textContent = titleMap[which] || 'Connections';

  _connPopoverRelease?.();
  const releaseTrap = trapFocus(pop);
  const releaseEsc = bindEscapeClose(pop, closeConnPopover);
  _connPopoverRelease = () => {
    releaseTrap();
    releaseEsc();
    _connPopoverRelease = null;
  };
  pop.querySelector('.conn-popover-close')?.focus();
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



function setSecretsBundleHint(text, isError = false) {
  const hint = document.getElementById('secretsBundleHint');
  if (!hint) return;
  hint.textContent = text || '';
  hint.classList.toggle('text-red-400', !!isError);
  hint.classList.toggle('text-slate-400', !isError);
}



function promptSecretsBundlePassphrase({ mode = 'export' } = {}) {
  return new Promise((resolve) => {
    const dialog = document.getElementById('secretsBundleDialog');
    const form = document.getElementById('secretsBundleDialogForm');
    const title = document.getElementById('secretsBundleDialogTitle');
    const help = document.getElementById('secretsBundleDialogHelp');
    const pw = document.getElementById('secretsBundlePassphrase');
    const confirmWrap = document.getElementById('secretsBundleConfirmWrap');
    const confirmPw = document.getElementById('secretsBundlePassphraseConfirm');
    const cancelBtn = document.getElementById('secretsBundleCancel');
    if (!dialog || !form || !pw) {
      resolve(null);
      return;
    }
    const isExport = mode === 'export';
    if (title) title.textContent = isExport ? 'Export bundle passphrase' : 'Import bundle passphrase';
    if (help) {
      help.textContent = isExport
        ? 'Choose a passphrase for this backup file. You will need it to import on another machine.'
        : 'Enter the passphrase you used when exporting this bundle.';
    }
    pw.value = '';
    if (confirmPw) confirmPw.value = '';
    if (confirmWrap) confirmWrap.classList.toggle('hidden', !isExport);
    const cleanup = () => {
      form.removeEventListener('submit', onSubmit);
      cancelBtn?.removeEventListener('click', onCancel);
      dialog.removeEventListener('close', onClose);
    };
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      cleanup();
      if (dialog.open) dialog.close();
      resolve(value);
    };
    const onCancel = (ev) => {
      ev.preventDefault();
      finish(null);
    };
    const onClose = () => {
      finish(null);
    };
    const onSubmit = (ev) => {
      ev.preventDefault();
      const value = pw.value || '';
      if (value.length < 8) {
        setSecretsBundleHint('Passphrase must be at least 8 characters.', true);
        return;
      }
      if (isExport && confirmPw && value !== confirmPw.value) {
        setSecretsBundleHint('Passphrases do not match.', true);
        return;
      }
      finish(value);
    };
    form.addEventListener('submit', onSubmit);
    cancelBtn?.addEventListener('click', onCancel);
    dialog.addEventListener('close', onClose);
    if (typeof dialog.showModal === 'function') dialog.showModal();
    else dialog.removeAttribute('hidden');
    pw.focus();
  });
}



async function exportSecretsBundle() {
  const passphrase = await promptSecretsBundlePassphrase({ mode: 'export' });
  if (!passphrase) return;
  setSecretsBundleHint('Exporting bundle…');
  try {
    const resp = await fetch('/api/auth/secrets/export', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ passphrase, include_profiles: true }),
    });
    if (!resp.ok) {
      let msg = `Export failed (${resp.status})`;
      try {
        const err = await resp.json();
        if (err?.error) msg = err.error;
      } catch (_) { /* binary or empty */ }
      setSecretsBundleHint(msg, true);
      return;
    }
    const blob = await resp.blob();
    const cd = resp.headers.get('Content-Disposition') || '';
    const match = cd.match(/filename="([^"]+)"/);
    const filename = match?.[1] || 'baklog-secrets.bundle';
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    setSecretsBundleHint('Bundle downloaded. Store it somewhere safe — we cannot recover the passphrase.');
  } catch (err) {
    setSecretsBundleHint(err?.message || 'Export failed.', true);
  }
}



async function importSecretsBundle(file) {
  if (!file) return;
  const passphrase = await promptSecretsBundlePassphrase({ mode: 'import' });
  if (!passphrase) return;
  setSecretsBundleHint('Importing bundle…');
  try {
    const buf = await file.arrayBuffer();
    const resp = await fetch(`/api/auth/secrets/import?passphrase=${encodeURIComponent(passphrase)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/octet-stream' },
      body: buf,
    });
    const payload = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      setSecretsBundleHint(payload?.error || `Import failed (${resp.status})`, true);
      return;
    }
    const nProv = (payload.providers_imported || []).length;
    const nProf = (payload.profiles_imported || []).length;
    setSecretsBundleHint(`Imported ${nProv} provider(s) and ${nProf} profile(s). Reloading…`);
    window.setTimeout(() => window.location.reload(), 1200);
  } catch (err) {
    setSecretsBundleHint(err?.message || 'Import failed.', true);
  }
}



function wireSecretsBundle() {
  const exportBtn = document.getElementById('secretsExportBtn');
  const importBtn = document.getElementById('secretsImportBtn');
  const importFile = document.getElementById('secretsImportFile');
  if (!exportBtn || !importBtn || !importFile) return;
  if (exportBtn.dataset.bound === '1') return;
  exportBtn.dataset.bound = '1';
  importBtn.dataset.bound = '1';
  exportBtn.addEventListener('click', () => { exportSecretsBundle(); });
  importBtn.addEventListener('click', () => {
    importFile.value = '';
    importFile.click();
  });
  importFile.addEventListener('change', () => {
    const file = importFile.files?.[0];
    if (file) importSecretsBundle(file);
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

  _authStatusLoaded = true;

  return authStatus;

}

/** True once /api/auth/status has resolved at least once this session. */
export function authStatusLoaded() {

  return _authStatusLoaded;

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

    void import('./filters-ui.js').then(({ applyItchTabVisibility }) => applyItchTabVisibility());

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

  return refreshConnections();

}



/** Map fetcher chip key -> auth provider for reconnect hints. */

export function providerForFetcher(key) {

  return FETCHER_AUTH_PROVIDER[key] || null;

}



export function noteFetcherAuthFailure(fetcherKey, logText) {

  const provider = providerForFetcher(fetcherKey);

  if (!provider) return false;

  const authish = /401|403|auth|cookie|session|credential|sign in|npsso|rejected/i.test(logText || '');

  if (authish) showReconnectBanner([provider]);

  return authish;

}



/** True when the given auth provider is currently connected (used to lift a

 * fetcher's auth-failure cooldown the moment the user reconnects). */

export function isProviderConnected(provider) {

  return authStatus.some(p => p.key === provider && p.status === 'connected');

}



/** Number of auth providers with status === 'connected' (onboarding / empty-state gate). */

export function connectedProviderCount() {

  return authStatus.filter(p => p.status === 'connected').length;

}



/** itch.io tab: show once API key is saved (connected/unverified) or library already loaded. */

export function isItchTabAvailable() {

  const row = authStatus.find(p => p.key === 'itch');

  const status = row?.status;

  const hasSetup = status === 'connected' || status === 'unverified';

  return hasSetup || (state.itchGames || []).length > 0;

}



/** Jump to Connections and start reconnect for a provider (browser auto-start). */
export async function reconnectProvider(provider) {

  if (!provider) return;

  _selectedKey = provider;

  document.querySelector('.view-tab[data-view="connections"]')?.click();

  try {

    await refreshConnections();

  } catch {

    renderConnections();

  }

  const p = authStatus.find(x => x.key === provider);

  const kind = p?.kind || 'browser';

  if (kind === 'browser') {

    await startBrowserConnect(provider);

  } else if (kind === 'manual') {

    await openManualUrl(provider);

  }

}

