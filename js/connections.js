import { baklogFetch, urlWithStreamTicket } from './api-client.js';
import { isAccountAuthMode, isPro } from './auth-gate.js';
import { renderConnectionsProLink } from './pro-view.js';
import { isPageHidden, registerPausable } from './visibility.js';
import { escapeAttr, escapeHtml, isSafeHttpUrl } from './dom-util.js';
import { bindEscapeClose, trapFocus } from './focus-trap.js';
import { FETCHER_AUTH_PROVIDER } from './fetcher-registry.js';
import { startMetrics, stopMetrics } from './anon-metrics.js';
import { savePrefs } from './prefs.js';
import { state } from './state.js';
import { storeLogoHtml } from './store-logos.js';
import { STORE_BRAND_COLORS } from './store-brand-colors.js';
import { formatPlatformList } from './platform-labels.js';
import {
  authStatusLoaded,
  connectedProviderCount,
  getAuthStatusSnapshot,
  ingestAuthStatusProviders,
  isItchTabAvailable,
  isProviderConnected,
  providerForFetcher,
  providerStatus,
} from './connections-status.js';

export { FETCHER_AUTH_PROVIDER };
export {
  authStatusLoaded,
  connectedProviderCount,
  ingestAuthStatusProviders,
  isItchTabAvailable,
  isProviderConnected,
  providerForFetcher,
  providerStatus,
};

let _chromiumAvailable = true;

const LOCAL_PROVIDER_FOOTER = {
  amazon: {
    connected: 'Auto-detected from Amazon Games launcher',
    disconnected: 'Launcher library hidden - Connect to use it again, or use Prime web',
  },
  gog_galaxy: {
    connected: 'Auto-detected from GOG Galaxy on this PC',
    disconnected: 'Galaxy library hidden - Connect to use it again, or use GOG (web)',
  },
  itch_local: {
    connected: 'Auto-detected from the itch desktop app',
    disconnected: 'Local itch library hidden - Connect to use it again, or use an API key',
  },
};

/** Footer copy for local provider cards (exported for tests). */
export function localProviderFooterCopy(providerKey, connected) {
  const copy = LOCAL_PROVIDER_FOOTER[providerKey];
  if (!copy) {
    return connected
      ? 'Auto-detected locally on this PC'
      : 'Local source hidden - Connect to use it again';
  }
  return connected ? copy.connected : copy.disconnected;
}

let _connPopoverRelease = null;

let reconnectProviders = new Set();

let pollTimer = null;
// True while refreshConnections() is running, so the baklog:auth-status listener
// (below) doesn't redundantly re-render — refreshConnections renders itself.
let _connRefreshInFlight = false;

const POST_CONNECT_FAST_POLL_MS = 3000;
const POST_CONNECT_FAST_POLL_MAX_MS = 30_000;
let postConnectFastPollTimer = null;
let postConnectFastPollStopAt = 0;

let gridWired = false;
let noteSaveTimer = null;

let chromeWired = false;

let _selectedKey = 'steam';

let _secretsCorrupt = false;

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



/** Map server status for pill/dot display (includes expired as its own state). */
export function displayStatus(serverStatus) {
  const st = serverStatus || 'disconnected';
  return st;
}



const STATUS_NOTE = {

  unverified: 'Found in .env but never verified. Click Verify to sign in.',

  expired: 'Last fetcher run reported an auth failure. Reconnect to refresh.',

  unavailable: 'Not available on this operating system.',

};



const PROVIDER_BRAND = {
  steam: { color: STORE_BRAND_COLORS.steam, initial: 'S' },
  gog: { color: STORE_BRAND_COLORS.gog, initial: 'G' },
  gog_galaxy: { color: STORE_BRAND_COLORS.gog, initial: 'G' },
  psn: { color: STORE_BRAND_COLORS.psn, initial: 'P' },
  epic: { color: STORE_BRAND_COLORS.epic, initial: 'E' },
  epic_wishlist: { color: STORE_BRAND_COLORS.epic, initial: 'E' },
  amazon: { color: STORE_BRAND_COLORS.amazon, initial: 'A' },
  amazon_web: { color: STORE_BRAND_COLORS.amazon, initial: 'A' },
  xbox: { color: STORE_BRAND_COLORS.xbox, initial: 'X' },
  xbox_wishlist: { color: STORE_BRAND_COLORS.xbox, initial: 'X' },
  battlenet: { color: STORE_BRAND_COLORS.battlenet, initial: 'B' },
  nintendo: { color: STORE_BRAND_COLORS.nintendo, initial: 'N' },
  nintendo_wishlist: { color: STORE_BRAND_COLORS.nintendo, initial: 'N' },
  ubisoft: { color: STORE_BRAND_COLORS.ubisoft, initial: 'U' },
  humble: { color: STORE_BRAND_COLORS.humble, initial: 'H' },
  ea: { color: STORE_BRAND_COLORS.ea, initial: 'EA' },
  itch: { color: STORE_BRAND_COLORS.itch, initial: 'I' },
  itch_local: { color: STORE_BRAND_COLORS.itch, initial: 'I' },
  itad: { color: '#22d3ee', initial: 'I' },
};



function connStoreKey(p) {
  // Collapse store variants onto the base brand badge (e.g. amazon_web -> amazon).
  return (p.key || '').replace(/_(wishlist|web|galaxy|local)$/, '');
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

/** What data this credential pulls (Content axis). */
const PROVIDER_CONTENT = {
  steam: 'both',
  gog: 'both',
  gog_galaxy: 'library',
  psn: 'both',
  xbox: 'library',
  xbox_wishlist: 'wishlist',
  epic: 'library',
  epic_wishlist: 'wishlist',
  amazon: 'library',
  amazon_web: 'library',
  nintendo: 'library',
  nintendo_wishlist: 'wishlist',
  itch: 'library',
  itch_local: 'library',
  battlenet: 'library',
  ubisoft: 'both',
  humble: 'both',
  ea: 'library',
  itad: 'deals',
};

const CONTENT_LABEL = {
  library: 'Library',
  wishlist: 'Wishlist',
  both: 'Library + Wishlist',
  deals: 'Deal prices',
};

function contentFacetLabel(key) {
  return CONTENT_LABEL[PROVIDER_CONTENT[key] || 'library'] || 'Library';
}

/** How credentials are obtained (Source axis). */
function sourceFacet(p) {
  if (p.kind === 'local') return 'File scan';
  if (p.kind === 'manual' || p.kind === 'form') return 'API key';
  return 'Web sign-in';
}

/** Collapsed rail entries: one button, multiple detail cards (library on top). */
const PROVIDER_GROUPS = {
  amazon: { label: 'Amazon', type: 'source', members: ['amazon_web', 'amazon'] },
  gog: { label: 'GOG', type: 'source', members: ['gog', 'gog_galaxy'] },
  itch: { label: 'itch.io', type: 'source', members: ['itch', 'itch_local'] },
  epic: { label: 'Epic', type: 'content', members: ['epic', 'epic_wishlist'] },
  xbox: { label: 'Xbox', type: 'content', members: ['xbox', 'xbox_wishlist'] },
  nintendo: { label: 'Nintendo', type: 'content', members: ['nintendo', 'nintendo_wishlist'] },
};
const GROUP_OF = Object.fromEntries(
  Object.entries(PROVIDER_GROUPS).flatMap(([g, d]) => d.members.map(k => [k, g])),
);
const STATUS_RANK = { connected: 4, expired: 3, unverified: 2, disconnected: 1, unavailable: 0 };

export function groupRepFor(key) {
  return GROUP_OF[key] || key;
}

export function combinedGroupStatus(members, groupKey) {
  const def = groupKey ? PROVIDER_GROUPS[groupKey] : null;
  if (def?.type === 'content') {
    // Library + wishlist are separate sign-ins; the rail status follows the library
    // card (listed first) so a connected wishlist cannot mask an expired library.
    const libraryKey = def.members[0];
    const library = (members || []).find(m => m.key === libraryKey);
    return library?.status || 'disconnected';
  }
  return (members || []).reduce((best, p) => {
    const st = p.status || 'disconnected';
    return (STATUS_RANK[st] ?? 0) > (STATUS_RANK[best] ?? 0) ? st : best;
  }, 'disconnected');
}

const GROUP_PILL_WORD = {
  expired: 'expired',
  disconnected: 'not connected',
  unverified: 'unverified',
  unavailable: 'unavailable',
};
const GROUP_PILL_ORDER = ['expired', 'disconnected', 'unverified', 'unavailable'];

/**
 * Rail pill for content groups (library + wishlist are separate sign-ins). A
 * single best/worst status can't tell the story when one member is connected
 * and the other expired, so summarise: green when every member is connected,
 * grey when nothing is set up yet, and an amber count pill ("1 expired",
 * "1 not connected", "1 expired · 1 not connected") for any partial/attention
 * state. Returns null for non-content groups (source groups like Amazon/GOG
 * where any one connected member is enough) and for empty member sets.
 */
export function groupRailPill(members, groupKey) {
  const def = groupKey ? PROVIDER_GROUPS[groupKey] : null;
  if (def?.type !== 'content') return null;
  const present = (members || []).filter(Boolean);
  if (!present.length) return null;
  const sts = present.map(m => m.status || 'disconnected');
  const connectedCount = sts.filter(s => s === 'connected').length;

  if (connectedCount === sts.length) {
    return { cls: STATUS_CLASS.connected, label: STATUS_LABEL.connected, dotState: 'connected' };
  }
  if (sts.every(s => s === 'disconnected' || s === 'unavailable')) {
    return { cls: STATUS_CLASS.disconnected, label: STATUS_LABEL.disconnected, dotState: 'disconnected' };
  }
  const counts = {};
  for (const s of sts) {
    if (s !== 'connected') counts[s] = (counts[s] || 0) + 1;
  }
  const label = GROUP_PILL_ORDER
    .filter(s => counts[s])
    .map(s => `${counts[s]} ${GROUP_PILL_WORD[s]}`)
    .join(' \u00b7 ');
  return { cls: STATUS_CLASS.expired, label, dotState: 'expired' };
}

/** Explanatory note above grouped provider cards (source vs content grouping). */
function groupConnectNote(groupKey, members) {
  const def = PROVIDER_GROUPS[groupKey];
  if (!def) return '';
  const anyConnected = (members || []).some(m => m.status === 'connected');
  if (def.type === 'content') {
    const lead = anyConnected
      ? `Ready to pull - at least one ${def.label} sign-in is connected.`
      : `Connect the library and/or wishlist cards below when you need them.`;
    return `<div class="conn-group-note"><p><strong>${escapeHtml(lead)}</strong></p><p>Library and wishlist are separate sign-ins for ${escapeHtml(def.label)}. They use different credentials - connect each one you want. The library card is on top.</p></div>`;
  }
  if (groupKey === 'amazon') {
    const lead = anyConnected
      ? 'Ready to pull - at least one source is connected.'
      : 'Connect the launcher or Prime web below to start pulling.';
    return `<div class="conn-group-note"><p><strong>${escapeHtml(lead)}</strong></p><p>You only need one Amazon source. Run the Amazon fetcher and BAKLOG auto-detects what's available - it scans the Amazon Games launcher database first (file scan) and falls back to Prime Gaming (web).</p></div>`;
  }
  if (groupKey === 'gog') {
    const lead = anyConnected
      ? 'Ready to pull - Galaxy and/or web session detected.'
      : 'Connect GOG (web) below, or install GOG Galaxy on Windows/macOS (Linux: web only).';
    return `<div class="conn-group-note"><p><strong>${escapeHtml(lead)}</strong></p><p>You only need one GOG source. Run the GOG fetcher and BAKLOG reads the Galaxy database first when present (file scan, library only), then falls back to your gog.com cookie session (web sign-in - library and wishlist).</p></div>`;
  }
  if (groupKey === 'itch') {
    const lead = anyConnected
      ? 'Ready to pull - itch app and/or API key detected.'
      : 'Install the itch desktop app, or paste an API key below.';
    const bundleNote = 'Heads up: games from itch.io bundles only sync after you claim them. Bundle items stay out of your library (and the itch app, so BAKLOG cannot see them) until you open each one from the bundle download page.';
    const bundleTip = 'Fast way to claim a whole bundle: open your bundle download page (itch.io my-purchases bundles), Ctrl+click (Cmd+click on Mac) every download button to open each in its own tab - that claims it to your library - then close all the tabs at once. Repeat per page.';
    return `<div class="conn-group-note"><p><strong>${escapeHtml(lead)}</strong></p><p>You only need one itch.io source. Run the itch fetcher and BAKLOG reads butler.db from the itch app first when present, then falls back to your API key.</p><p>${escapeHtml(bundleNote)}</p><p>${escapeHtml(bundleTip)}</p></div>`;
  }
  return '';
}

function railSortIndex(key) {
  const idx = RAIL_ORDER.indexOf(key);
  return idx >= 0 ? idx : RAIL_ORDER.length;
}

function orderedProviders() {
  const steam = getAuthStatusSnapshot().find(p => p.key === 'steam');
  const rest = getAuthStatusSnapshot()
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
      .map(k => getAuthStatusSnapshot().find(x => x.key === k))
      .filter(Boolean);
    out.push({
      key: g,
      label: PROVIDER_GROUPS[g].label,
      status: combinedGroupStatus(members, g),
      available: members.some(m => m.available !== false),
      _group: true,
      _members: members,
    });
  }
  return out;
}

function ensureSelectedKey() {
  if (getAuthStatusSnapshot().some(p => p.key === _selectedKey)) return;
  const rep = groupRepFor(_selectedKey);
  if (
    PROVIDER_GROUPS[rep]
    && PROVIDER_GROUPS[rep].members.some(k => getAuthStatusSnapshot().some(p => p.key === k))
  ) {
    _selectedKey = rep;
    return;
  }
  const steam = getAuthStatusSnapshot().find(p => p.key === 'steam');
  _selectedKey = steam?.key || getAuthStatusSnapshot()[0]?.key || 'steam';
}



function renderHero() {

  const countEl = document.getElementById('connHeroCount');

  const fillEl = document.getElementById('connProgressFill');

  if (!countEl || !fillEl) return;

  if (!getAuthStatusSnapshot().length) {

    countEl.textContent = 'Loading connections…';

    fillEl.style.width = '0%';

    return;

  }

  const connected = connectedProviderCount();

  const total = getAuthStatusSnapshot().length;

  countEl.textContent = `${connected} of ${total} connections made`;

  fillEl.style.width = total ? `${(connected / total) * 100}%` : '0%';

}



function renderOnboard() {

  const el = document.getElementById('connOnboard');

  if (!el) return;

  if (!getAuthStatusSnapshot().length || connectedProviderCount() > 0) {

    el.innerHTML = '';

    el.hidden = true;

    return;

  }

  el.hidden = false;

  el.innerHTML = `

    <div class="conn-onboard" role="region" aria-label="Get started">

      <p class="conn-onboard-title">You have 0 stores connected</p>

      <p class="conn-onboard-lead">Start with Steam - it imports your whole library in one sign-in. You can add the rest after.</p>

      <button type="button" class="conn-onboard-btn" data-conn-start-steam title="Connect Steam - imports your library via browser sign-in">Start with Steam</button>

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
  const epicBrowser = p.key === 'epic'
    ? `<button type="button" class="conn-open-url" data-epic-oauth data-provider="epic" title="Epic library OAuth in browser">Sign in with your browser instead</button>`
    : '';
  return `
    <details class="conn-fallback">
      <summary class="conn-fallback-summary">
        <span class="conn-fallback-chevron" aria-hidden="true">&rsaquo;</span>
        <span>Trouble connecting? Enter a code manually</span>
      </summary>
      <div class="conn-fallback-body">
        ${epicBrowser}
        ${buildFormPanel(p)}
      </div>
    </details>`;
}


function disconnectBtnHtml(p, st) {
  const show = st !== 'disconnected' && st !== 'unverified' && p.kind !== 'local';
  return show
    ? `<button type="button" class="conn-disconnect" data-disconnect-quick data-provider="${escapeAttr(p.key)}" title="Disconnect ${escapeAttr(p.label)} (credentials removed locally)">Disconnect</button>`
    : '';
}


function buildCardFooter(p, st) {

  if (p.available === false) {
    const plats = formatPlatformList(p.platforms);
    return `
      <div class="conn-card-footer">
        <span class="conn-local-label">${escapeHtml(`Available on ${plats} only`)}</span>
      </div>`;
  }

  if (p.kind === 'local') {
    const connected = st === 'connected';
    const label = localProviderFooterCopy(p.key, connected);
    return `
      <div class="conn-card-footer">
        ${connected
          ? `<span class="conn-local-label">${escapeHtml(label)}</span>
             <button type="button" class="conn-disconnect" data-disconnect-quick data-provider="${escapeAttr(p.key)}" title="Disconnect ${escapeAttr(p.label)} (credentials removed locally)">Disconnect</button>`
          : `<span class="conn-local-label">${escapeHtml(label)}</span>
             <button type="button" class="conn-primary" data-enable-local data-provider="${escapeAttr(p.key)}" title="Enable ${escapeAttr(p.label)} from local launcher data">Connect</button>`
        }
      </div>`;
  }



  if (p.kind === 'manual') {

    return `

      <div class="conn-card-footer">

        <button type="button" class="conn-open-url" data-open-url data-provider="${escapeAttr(p.key)}" title="Open ${escapeAttr(p.label)} sign-in page in browser">Open sign-in page</button>

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

      log.textContent = 'Could not read clipboard - paste into the field manually (Ctrl+V).';

    }

  }

}



function buildCardHtml(p) {

  const st = p.status || 'disconnected';

  const pillSt = displayStatus(st);

  const storeKey = connStoreKey(p);

  const expiry = p.expiry_days ? `<p class="conn-meta">Typical session ~${p.expiry_days}d</p>` : '';

  const note = STATUS_NOTE[st] ? `<p class="conn-note">${escapeHtml(STATUS_NOTE[st])}</p>` : '';

  const err = p.last_error ? `<p class="conn-error">${escapeHtml(p.last_error)}</p>` : '';

  const tips = (p.tips || []).length
    ? `<ul class="conn-tips">${p.tips.map(t => `<li>${escapeHtml(t)}</li>`).join('')}</ul>`
    : '';

  const hasFormFields = (p.form_fields || []).length > 0;

  const showFormPanel = hasFormFields && (p.kind === 'form' || p.kind === 'manual' || p.kind === 'browser');

  const facets = `
    <div class="conn-facets" aria-label="Pull type and credential source">
      <span class="conn-facet conn-facet--content" title="What this connection syncs (library, wishlist, prices)">${escapeHtml(contentFacetLabel(p.key))}</span>
      <span class="conn-facet conn-facet--source" title="Where credentials are stored">${escapeHtml(sourceFacet(p))}</span>
    </div>`;

  const noteVal = (state.prefs?.connectionNotes || {})[p.key] || '';
  const notesHtml = `
    <div class="conn-notes">
      <label class="conn-notes-label" for="conn-note-${escapeAttr(p.key)}">Notes</label>
      <textarea id="conn-note-${escapeAttr(p.key)}" class="conn-note-input"
        data-note-provider="${escapeAttr(p.key)}" rows="2"
        placeholder="Private notes for this connection (saved to this profile)">${escapeHtml(noteVal)}</textarea>
    </div>`;

  return `

    <article class="conn-card${p.kind === 'manual' ? ' conn-card--manual' : ''}" data-provider="${escapeAttr(p.key)}">

      <div class="conn-card-stripe"></div>

      <div class="conn-card-head">

        ${storeLogoHtml(storeKey, { size: 'lg', title: p.label, className: 'conn-card-badge' })}

        <div class="conn-head-actions">

          <span class="${STATUS_CLASS[pillSt] || STATUS_CLASS.disconnected}" title="Connection status">${STATUS_LABEL[pillSt] || pillSt}</span>

        </div>

      </div>

      <div class="conn-card-body">

        <div class="conn-card-body-main">

          <h3>${escapeHtml(p.label)}</h3>

          ${facets}

          <p class="conn-desc">${escapeHtml(p.description || '')}</p>

          ${tips}

          ${note}

          ${err}

          ${expiry}

          <p class="conn-log hidden" aria-live="polite"></p>

        </div>

        ${notesHtml}

      </div>

      ${showFormPanel ? (p.kind === 'browser' ? buildFallbackPanel(p) : buildFormPanel(p)) : ''}

      ${buildCardFooter(p, st)}

    </article>`;

}



function buildRailItemHtml(p, selected) {

  const st = p.status || 'disconnected';

  const pillSt = displayStatus(st);

  const storeKey = connStoreKey(p);

  const sel = selected ? ' is-selected' : '';

  const unavailable = p.available === false;

  const unav = unavailable ? ' is-unavailable' : '';

  const title = unavailable
    ? `${p.label} is available on ${formatPlatformList(p.platforms)} only`
    : `Select ${p.label} to connect or manage`;

  // Content groups (library + wishlist) summarise both members in one amber
  // count pill; everything else uses the single-status pill.
  const groupPill = p._group ? groupRailPill(p._members, p.key) : null;
  const dotState = groupPill ? groupPill.dotState : pillSt;
  const pillCls = groupPill ? groupPill.cls : (STATUS_CLASS[pillSt] || STATUS_CLASS.disconnected);
  const pillLabel = groupPill ? groupPill.label : (STATUS_LABEL[pillSt] || pillSt);

  return `

    <div class="conn-rail-item${sel}${unav}" data-provider="${escapeAttr(p.key)}" role="option" tabindex="${selected ? '0' : '-1'}" aria-selected="${selected ? 'true' : 'false'}" title="${escapeAttr(title)}">

      <span class="conn-row-dot conn-row-dot--${escapeAttr(dotState)}" aria-hidden="true" title="Status: green=connected, amber=unverified, red=expired"></span>

      ${storeLogoHtml(storeKey, { size: 'sm', title: p.label, className: 'conn-rail-badge' })}

      <span class="conn-row-label">${escapeHtml(p.label)}</span>

      <span class="${pillCls} conn-row-pill" title="Connection status">${escapeHtml(pillLabel)}</span>

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



function captureConnNoteFocus() {
  const active = document.activeElement;
  if (!active?.classList?.contains('conn-note-input')) return null;
  return {
    provider: active.dataset.noteProvider,
    selStart: active.selectionStart,
    selEnd: active.selectionEnd,
  };
}

function restoreConnNoteFocus(focusState, root) {
  if (!focusState?.provider || !root) return;
  const ta = root.querySelector(`.conn-note-input[data-note-provider="${focusState.provider}"]`);
  if (!ta) return;
  ta.focus();
  try {
    ta.setSelectionRange(focusState.selStart, focusState.selEnd);
  } catch {
    // setSelectionRange can fail on some browsers during rapid re-render
  }
}



function renderConnPrefs() {
  const onConnect = document.getElementById('autoFetchOnConnectToggle');
  const stale24h = document.getElementById('autoFetchStale24hToggle');
  const shareStats = document.getElementById('shareAnonStatsToggle');
  if (onConnect) onConnect.checked = state.prefs.autoFetchOnConnect !== false;
  if (stale24h) stale24h.checked = state.prefs.autoFetchStale24h === true;
  if (shareStats) shareStats.checked = state.prefs.shareAnonStats === true;

  const note = document.getElementById('bgRefreshPlanNote');
  if (note) {
    if (isPro()) {
      note.textContent =
        'Pro: background refresh keeps stale stores fresh even when BAKLOG is closed to the tray.';
      note.classList.add('conn-prefs-note--pro');
    } else {
      note.textContent =
        'Auto-refresh runs while BAKLOG is open (even minimized). Pro adds background refresh while closed to the tray.';
      note.classList.remove('conn-prefs-note--pro');
    }
    note.hidden = false;
  }
}

function renderConnections() {

  const rail = document.getElementById('connRail');

  const pane = document.getElementById('connPane');

  if (!rail || !pane) return;

  renderHero();

  renderConnPrefs();

  renderConnectionsProLink();

  renderOnboard();

  if (!getAuthStatusSnapshot().length) {

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

  const noteFocus = captureConnNoteFocus();

  if (PROVIDER_GROUPS[selKey]) {
    const members = PROVIDER_GROUPS[selKey].members
      .map(k => getAuthStatusSnapshot().find(x => x.key === k))
      .filter(Boolean);
    const note = groupConnectNote(selKey, members);
    pane.innerHTML = `${note}<div class="conn-card-stack">${members.map(buildCardHtml).join('')}</div>`;
  } else {
    const selected = getAuthStatusSnapshot().find(p => p.key === selKey);
    pane.innerHTML = selected
      ? buildCardHtml(selected)
      : '<p class="text-sm text-slate-400">Select a provider on the left to get started.</p>';
  }

  restoreConnNoteFocus(noteFocus, pane);

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

    runConnAction(provider, () => disconnectProvider(provider));

    return;

  }



  const pasteBtn = target.closest('[data-paste-clipboard]');

  if (pasteBtn && card) {

    pasteFromClipboard(card);

    return;

  }



  const epicOauthBtn = target.closest('[data-epic-oauth]');

  if (epicOauthBtn) {

    startEpicBrowserOAuth();

    return;

  }



  const openUrlBtn = target.closest('[data-open-url]');

  if (openUrlBtn && provider) {

    openManualUrl(provider);

    return;

  }



  const enableLocalBtn = target.closest('[data-enable-local]');

  if (enableLocalBtn?.dataset.provider) {

    runConnAction(enableLocalBtn.dataset.provider, () => enableLocalProvider(enableLocalBtn.dataset.provider));

    return;

  }



  const primaryBtn = target.closest('.conn-primary');

  if (primaryBtn?.dataset.provider) {
    runConnAction(primaryBtn.dataset.provider, () => startBrowserConnect(primaryBtn.dataset.provider));

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

  if (!railItem || !getAuthStatusSnapshot().length) return;



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

  container.addEventListener('input', (ev) => {
    const ta = ev.target.closest('.conn-note-input');
    if (!ta) return;
    const provider = ta.dataset.noteProvider;
    if (!provider) return;
    if (!state.prefs.connectionNotes) state.prefs.connectionNotes = {};
    state.prefs.connectionNotes[provider] = ta.value;
    clearTimeout(noteSaveTimer);
    noteSaveTimer = setTimeout(() => savePrefs(), 500);
  });

  container.addEventListener('change', (ev) => {
    if (ev.target.id === 'autoFetchOnConnectToggle') {
      state.prefs.autoFetchOnConnect = ev.target.checked;
      savePrefs();
    } else if (ev.target.id === 'autoFetchStale24hToggle') {
      state.prefs.autoFetchStale24h = ev.target.checked;
      savePrefs();
    } else if (ev.target.id === 'shareAnonStatsToggle') {
      state.prefs.shareAnonStats = ev.target.checked;
      savePrefs();
      if (ev.target.checked) startMetrics();
      else stopMetrics();
    }
  });

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

    try {

      const res = await baklogFetch('/api/auth/master-password', {

        method: 'POST',

        headers: { 'Content-Type': 'application/json' },

        body: JSON.stringify({ password: pw || null }),

      });

      const hint = document.getElementById('masterPasswordHint');

      if (!res.ok) {

        const data = await res.json().catch(() => ({}));

        if (hint) hint.textContent = data.error || `Save failed (${res.status})`;

        return;

      }

      if (hint) hint.textContent = pw ? 'Master password set (portable encryption).' : 'Using OS keychain.';

    } catch (_) {

      const hint = document.getElementById('masterPasswordHint');

      if (hint) hint.textContent = 'Could not reach the local server.';

    }

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
    const resp = await baklogFetch('/api/auth/secrets/export', {
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
    setSecretsBundleHint('Bundle downloaded. Store it somewhere safe - we cannot recover the passphrase.');
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
    const bytes = new Uint8Array(buf);
    let binary = '';
    const chunk = 0x8000;
    for (let i = 0; i < bytes.length; i += chunk) {
      binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
    }
    const blobB64 = btoa(binary);
    const resp = await baklogFetch('/api/auth/secrets/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ passphrase, blob: blobB64 }),
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

  });

  // Close the kebab menu on any click outside it (the section-scoped handler
  // above only fires for clicks inside #connectionsContainer, so clicks on the
  // header or elsewhere on the page would otherwise leave the menu open).
  document.addEventListener('click', ev => {

    const menu = document.getElementById('connKebabMenu');

    if (!menu || menu.hidden) return;

    const target = ev.target;

    if (target.closest('#connKebabMenu') || target.closest('#connKebabBtn')) return;

    toggleKebabMenu(false);

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

export function clearReconnectBanner(provider) {
  if (!provider) return;
  if (reconnectProviders.delete(provider)) renderReconnectBanner();
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

    .map(k => getAuthStatusSnapshot().find(p => p.key === k)?.label || k)

    .join(', ');

  el.classList.remove('hidden');

  el.innerHTML = `

    <span>Session expired for <strong>${escapeHtml(names)}</strong>.</span>

    <button type="button" class="underline ml-2" data-jump-connections title="Open Connections to refresh expired sessions">Reconnect in Connections</button>

    <button type="button" class="ml-2 opacity-70" data-dismiss-auth-banner aria-label="Dismiss" title="Dismiss session expired banner">&times;</button>

  `;

  el.querySelector('[data-jump-connections]')?.addEventListener('click', () => {

    const first = reconnectProviders.values().next().value;

    if (first) _selectedKey = first;

    document.querySelector('.view-tab[data-view="connections"]')?.click();

    renderConnections();

  });

  el.querySelector('[data-dismiss-auth-banner]')?.addEventListener('click', () => {
    const providers = [...reconnectProviders];
    reconnectProviders.clear();
    renderReconnectBanner();
    try {
      document.dispatchEvent(
        new CustomEvent('baklog:reconnect-dismiss', { detail: { providers } }),
      );
    } catch (_) { /* no DOM (tests) */ }
  });

}



function connectionStatusErrorMessage(err) {
  const status = err?.status;
  if (status === 401) {
    return isAccountAuthMode()
      ? 'Session expired or not signed in. Sign in again to refresh connection status.'
      : 'Not authorized to load connection status.';
  }
  if (status === 503) return 'Server secrets store is unavailable. Check server logs.';
  if (status >= 500) {
    return err?.detail
      ? `Server error loading connection status: ${err.detail}`
      : 'Server error loading connection status. Check server.py logs.';
  }
  if (err?.code === 'network') {
    return 'Could not reach the local server (is server.py running?).';
  }
  return 'Could not load connection status.';
}


function ensureConnRefreshBanner() {
  const layout = document.getElementById('connLayout');
  if (!layout) return null;
  let el = document.getElementById('connRefreshBanner');
  if (!el) {
    el = document.createElement('p');
    el.id = 'connRefreshBanner';
    el.className = 'conn-refresh-error text-sm text-amber-400 hidden';
    el.setAttribute('role', 'status');
    layout.parentNode?.insertBefore(el, layout);
  }
  return el;
}


function showConnRefreshError(msg) {
  const el = ensureConnRefreshBanner();
  if (!el) return;
  el.textContent = msg;
  el.classList.remove('hidden');
}


function clearConnRefreshError() {
  const el = document.getElementById('connRefreshBanner');
  if (el) el.classList.add('hidden');
}


async function fetchAuthStatus() {
  let res;
  try {
    res = await baklogFetch('/api/auth/status');
  } catch (_) {
    const err = new Error('network');
    err.code = 'network';
    throw err;
  }
  if (!res.ok) {
    const err = new Error(`auth status ${res.status}`);
    err.status = res.status;
    try {
      const body = await res.json();
      if (body?.error) err.detail = body.error;
    } catch { /* ignore */ }
    throw err;
  }
  const data = await res.json();
  _secretsCorrupt = !!data.secrets_corrupt;
  renderSecretsCorruptBanner();
  ingestAuthStatusProviders(data.providers || []);
  return getAuthStatusSnapshot();
}

/** True when the server secrets bundle is corrupt (see GET /api/auth/status). */
export function secretsStoreCorrupt() {
  return _secretsCorrupt;
}

function renderSecretsCorruptBanner() {
  const el = document.getElementById('authSecretsBanner');
  if (!el) return;
  if (!_secretsCorrupt) {
    el.classList.add('hidden');
    el.innerHTML = '';
    return;
  }
  el.classList.remove('hidden');
  el.innerHTML = `
    <span><strong>Secrets store corrupt.</strong> Re-export from a backup or re-enter credentials on the Connections page.</span>
    <button type="button" class="underline ml-2" data-jump-connections-secrets>Open Connections</button>
  `;
  el.querySelector('[data-jump-connections-secrets]')?.addEventListener('click', () => {
    document.querySelector('.view-tab[data-view="connections"]')?.click();
  });
}

async function openManualUrl(provider) {

  const card = document.querySelector(`.conn-card[data-provider="${provider}"]`);

  const log = card?.querySelector('.conn-log');

  if (log) {

    log.classList.remove('hidden');

    log.textContent = 'Opening in your default browser…';

  }

  const res = await baklogFetch(`/api/auth/${provider}/open-url`, { method: 'POST' });

  const data = await res.json().catch(() => ({}));

  if (!res.ok) {

    if (log) log.textContent = data.error || `Could not open browser (${res.status})`;

    return;

  }

  if (log) log.textContent = 'Copy your API key from the browser tab, paste above, then Save key.';

}



async function startEpicBrowserOAuth() {

  const card = document.querySelector('.conn-card[data-provider="epic"]');

  const log = card?.querySelector('.conn-log');

  if (log) {

    log.classList.remove('hidden');

    log.textContent = 'Opening Epic sign-in…';

  }

  let res;

  try {

    res = await baklogFetch('/api/auth/epic/oauth-url', { method: 'POST' });

  } catch (_) {

    if (log) log.textContent = 'Could not reach the local server (is server.py running?).';

    return;

  }

  const data = await res.json().catch(() => ({}));

  if (!res.ok || !data.url) {

    if (log) log.textContent = data.error || `Could not start Epic sign-in (${res.status})`;

    return;

  }

  if (!isSafeHttpUrl(data.url)) {

    if (log) log.textContent = 'Epic returned an unexpected sign-in URL; aborting.';

    return;

  }

  window.open(data.url, '_blank', 'noopener');

  startPostConnectFastPoll();

  if (log) log.textContent = 'Finish signing in in the new tab - this page updates once Epic connects.';

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

  const res = await baklogFetch(`/api/auth/${provider}/credentials`, {

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



function connLogError(provider, message) {

  const card = document.querySelector(`.conn-card[data-provider="${provider}"]`);

  const log = card?.querySelector('.conn-log');

  if (log) {

    log.classList.remove('hidden');

    log.textContent = message;

  }

}



function runConnAction(provider, fn) {

  void fn().catch(err => {

    connLogError(provider, err?.message || 'Action failed');

  });

}



async function disconnectProvider(provider) {

  const card = document.querySelector(`.conn-card[data-provider="${provider}"]`);

  const log = card?.querySelector('.conn-log');

  let res;

  try {

    res = await baklogFetch(`/api/auth/${provider}/disconnect`, { method: 'POST' });

  } catch (_) {

    if (log) {

      log.classList.remove('hidden');

      log.textContent = 'Could not reach the local server (is server.py running?).';

    }

    return;

  }

  if (!res.ok) {

    const data = await res.json().catch(() => ({}));

    if (log) {

      log.classList.remove('hidden');

      log.textContent = data.error || `Disconnect failed (${res.status})`;

    }

    return;

  }

  reconnectProviders.delete(provider);

  renderReconnectBanner();

  await refreshConnections();

}



/** Enable a local-only provider (e.g. Amazon launcher) by verifying its
 *  on-disk source exists server-side. No browser sign-in — POST /enable
 *  validates the local data and marks the provider connected. */
async function enableLocalProvider(provider) {

  const card = document.querySelector(`.conn-card[data-provider="${provider}"]`);

  const log = card?.querySelector('.conn-log');

  if (log) {

    log.classList.remove('hidden');

    log.textContent = 'Checking for local data on this PC…';

  }

  let res;

  try {

    res = await baklogFetch(`/api/auth/${provider}/enable`, { method: 'POST' });

  } catch (_) {

    if (log) log.textContent = 'Could not reach the local server (is server.py running?).';

    return;

  }

  const data = await res.json().catch(() => ({}));

  if (!res.ok) {

    if (log) log.textContent = data.error || `Could not enable (${res.status})`;

    return;

  }

  reconnectProviders.delete(provider);

  renderReconnectBanner();

  await refreshConnections();

}



async function startBrowserConnect(provider) {

  const card = document.querySelector(`.conn-card[data-provider="${provider}"]`);

  const log = card?.querySelector('.conn-log');

  // A "Reconnect" (status connected/expired) should start a clean sign-in:
  // wipe the old profile cookies server-side so a stale/expired session never
  // carries over. A first-time Connect has nothing to clear.
  // Epic wishlist keeps its browser profile on reconnect — cf_clearance and
  // storefront cookies must survive or Cloudflare re-challenges every time.
  const current = getAuthStatusSnapshot().find(x => x.key === provider)?.status;
  const preserveProfile = provider === 'epic_wishlist';
  const fresh = !preserveProfile && (current === 'connected' || current === 'expired');

  if (log) {

    log.classList.remove('hidden');

    log.textContent = fresh ? 'Clearing old session, opening sign-in window…' : 'Opening sign-in window…';

  }

  let res;

  try {

    res = await baklogFetch(`/api/auth/${provider}/start${fresh ? '?fresh=1' : ''}`, { method: 'POST' });

  } catch (err) {
    if (log) log.textContent = 'Could not reach the local server (is server.py running?).';

    return;

  }

  const data = await res.json().catch(() => ({}));

  if (!res.ok) {

    if (log) log.textContent = data.error || `Start failed (${res.status})`;

    return;

  }

  startPostConnectFastPoll();

  const streamUrl = await urlWithStreamTicket(`/api/auth/${data.session_id}/stream`);
  const es = new EventSource(streamUrl);

  es.addEventListener('waiting_for_user', ev => {

    const msg = JSON.parse(ev.data);

    if (log) log.textContent = msg.message || 'Complete sign-in in the browser window…';

  });

  es.addEventListener('signed_in', () => {

    if (log) log.textContent = 'Signed in - extracting credentials…';

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



async function refreshBrowserPreflight() {
  try {
    const res = await baklogFetch('/api/config');
    if (!res.ok) return;
    const data = await res.json();
    if (typeof data.chromium_available === 'boolean') {
      _chromiumAvailable = data.chromium_available;
    }
  } catch {
    // Older servers omit chromium_available — assume available.
  }
}

function renderBrowserWarn() {
  const el = document.getElementById('connBrowserWarn');
  if (!el) return;
  if (_chromiumAvailable) {
    el.hidden = true;
    el.innerHTML = '';
    return;
  }
  el.hidden = false;
  el.innerHTML = `
    <div class="migration-banner-body">
      <span class="text-amber-400">Google Chrome or Microsoft Edge is required for store sign-in. Install one, then click Connect.</span>
    </div>`;
}

export async function refreshConnections() {

  _connRefreshInFlight = true;
  try {

    await refreshBrowserPreflight();
    await fetchAuthStatus();

    clearConnRefreshError();

    renderConnections();
    renderBrowserWarn();

    renderReconnectBanner();

    const { applyItchTabVisibility } = await import('./filters-ui.js');
    applyItchTabVisibility();

  } catch (err) {

    const msg = connectionStatusErrorMessage(err);

    if (getAuthStatusSnapshot().length > 0) {

      renderConnections();

      showConnRefreshError(msg);

    } else {

      clearConnRefreshError();

      const rail = document.getElementById('connRail');

      const pane = document.getElementById('connPane');

      if (rail) rail.innerHTML = '';

      if (pane) {

        pane.innerHTML = `<p class="text-sm text-amber-400">${escapeHtml(msg)}</p>`;

      }

    }

    renderHero();

  } finally {

    _connRefreshInFlight = false;

  }

}



function startPostConnectFastPoll() {
  stopPostConnectFastPoll();
  postConnectFastPollStopAt = Date.now() + POST_CONNECT_FAST_POLL_MAX_MS;
  refreshConnections();
  postConnectFastPollTimer = setInterval(() => {
    if (isPageHidden()) return;
    if (Date.now() >= postConnectFastPollStopAt) {
      stopPostConnectFastPoll();
      return;
    }
    refreshConnections();
  }, POST_CONNECT_FAST_POLL_MS);
}

function stopPostConnectFastPoll() {
  if (postConnectFastPollTimer) clearInterval(postConnectFastPollTimer);
  postConnectFastPollTimer = null;
  postConnectFastPollStopAt = 0;
}

function resumePostConnectFastPollIfActive() {
  if (postConnectFastPollStopAt <= Date.now()) return;
  if (postConnectFastPollTimer) return;
  postConnectFastPollTimer = setInterval(() => {
    if (isPageHidden()) return;
    if (Date.now() >= postConnectFastPollStopAt) {
      stopPostConnectFastPoll();
      return;
    }
    refreshConnections();
  }, POST_CONNECT_FAST_POLL_MS);
}


export function startConnectionsPolling() {
  stopConnectionsPolling();
  if (state.activeView !== 'connections' || isPageHidden()) return;
  pollTimer = setInterval(() => {
    if (state.activeView !== 'connections' || isPageHidden()) return;
    refreshConnections();
  }, 15000);
}

if (typeof document !== 'undefined') {
  registerPausable({
    pause() {
      stopConnectionsPolling();
      if (postConnectFastPollTimer) {
        clearInterval(postConnectFastPollTimer);
        postConnectFastPollTimer = null;
      }
    },
    resume() {
      if (state.activeView === 'connections') startConnectionsPolling();
      resumePostConnectFastPollIfActive();
    },
  });

  if (typeof BroadcastChannel !== 'undefined') {
    try {
      const authChannel = new BroadcastChannel('baklog-auth');
      authChannel.onmessage = (ev) => {
        if (ev.data?.provider) refreshConnections();
      };
    } catch (_) { /* ignore */ }
  }

  // Repaint the open Connections view the instant the auth-status cache changes
  // out-of-band (e.g. a fetcher run just failed with 401 and the fast path called
  // ingestAuthStatusProviders), instead of waiting up to 15s for the next poll.
  // Skip when our own refreshConnections() drove the update — it renders itself.
  document.addEventListener('baklog:auth-status', () => {
    if (_connRefreshInFlight) return;
    if (state.activeView !== 'connections' || isPageHidden()) return;
    try {
      renderConnections();
      renderReconnectBanner();
    } catch (_) { /* view not mounted */ }
  });
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



export function noteFetcherAuthFailure(fetcherKey, logText) {

  const provider = providerForFetcher(fetcherKey);

  if (!provider) return false;

  const authish = /401|403|auth|cookie|session|credential|sign in|npsso|rejected/i.test(logText || '');

  if (authish) showReconnectBanner([provider]);

  return authish;

}



/** Jump to Connections and start reconnect for a provider (browser auto-start). */
export async function reconnectProvider(provider, { autoStart = true } = {}) {

  if (!provider) return;

  _selectedKey = groupRepFor(provider);

  document.querySelector('.view-tab[data-view="connections"]')?.click();

  try {

    await refreshConnections();

  } catch {

    renderConnections();

  }

  // When navigating in from a dashboard chip/affordance we only want to tab
  // over to the right card so the user can choose - never auto-open a sign-in
  // window or trigger a local scan. autoStart stays on for explicit in-page
  // connect actions (e.g. Steam onboarding button).
  if (!autoStart) return;

  const p = getAuthStatusSnapshot().find(x => x.key === provider);

  const kind = p?.kind || 'browser';

  if (kind === 'local') {

    await enableLocalProvider(provider);

  } else if (kind === 'browser') {

    await startBrowserConnect(provider);

  } else if (kind === 'manual') {

    await openManualUrl(provider);

  }

}

