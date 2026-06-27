/**
 * Connections left-rail: provider grouping, status pills, and rail HTML.
 * Session flows (connect/disconnect, polling, bundles) stay in connections.js.
 */
import { escapeAttr, escapeHtml } from './dom-util.js';
import { formatPlatformList } from './platform-labels.js';
import { getAuthStatusSnapshot } from './connections-status.js';
import { storeLogoHtml } from './store-logos.js';

export const STATUS_LABEL = {
  connected: 'Connected',
  unverified: 'Unverified',
  disconnected: 'Not connected',
  expired: 'Session expired',
  unavailable: 'Unavailable',
};

export const STATUS_CLASS = {
  connected: 'conn-pill conn-pill--ok',
  unverified: 'conn-pill conn-pill--unverified',
  disconnected: 'conn-pill conn-pill--off',
  expired: 'conn-pill conn-pill--warn',
  unavailable: 'conn-pill conn-pill--off',
};

/** Map server status for pill/dot display (includes expired as its own state). */
export function displayStatus(serverStatus) {
  return serverStatus || 'disconnected';
}

export const STATUS_NOTE = {
  unverified: 'Found in .env but never verified. Click Verify to sign in.',
  expired: 'Last fetcher run reported an auth failure. Reconnect to refresh.',
  unavailable: 'Not available on this operating system.',
};

/**
 * Rail order after Steam, sorted by ease of use (smoothest first), with each
 * company's library + wishlist kept adjacent and the library always first.
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

export function connStoreKey(p) {
  return (p.key || '').replace(/_(wishlist|web|galaxy|local)$/, '');
}

export function contentFacetLabel(key) {
  return CONTENT_LABEL[PROVIDER_CONTENT[key] || 'library'] || 'Library';
}

/** How credentials are obtained (Source axis). */
export function sourceFacet(p) {
  if (p.kind === 'local') return 'File scan';
  if (p.kind === 'manual' || p.kind === 'form') return 'API key';
  return 'Web sign-in';
}

/** Collapsed rail entries: one button, multiple detail cards (library on top). */
export const PROVIDER_GROUPS = {
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
export function groupConnectNote(groupKey, members) {
  const def = PROVIDER_GROUPS[groupKey];
  if (!def) return '';
  const anyConnected = (members || []).some(m => m.status === 'connected');
  if (groupKey === 'nintendo') {
    const lead = anyConnected
      ? 'Ready to pull - at least one Nintendo sign-in is connected.'
      : 'Connect the library and/or wishlist cards below when you need them.';
    const legacyNote = 'Library sync uses Virtual Game Cards for your full digital entitlement list, plus eShop receipts for purchase dates. Nintendo receipts only cover about two years; BAKLOG keeps older digital purchases in your library across syncs - they are not marked stale. Use bulk Remove on a row if you want a title gone for good. Physical cartridges are not included.';
    return `<div class="conn-group-note"><p><strong>${escapeHtml(lead)}</strong></p><p>Library and wishlist are separate sign-ins for Nintendo. They use different credentials - connect each one you want. The library card is on top.</p><p>${escapeHtml(legacyNote)}</p></div>`;
  }
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
    return `<div class="conn-group-note"><p><strong>${escapeHtml(lead)}</strong></p><p>You only need one Amazon source. Run the Amazon fetcher and BAKLOG auto-detects what's available - launcher database first, then Prime web.</p><p><strong>Launcher:</strong> open the Amazon Games app and let it sync before you fetch. BAKLOG only reads what's already in the local database and does not refresh it in the background.</p><p><strong>Prime web:</strong> uses your saved sign-in and fetches headless - no launcher needed. It only imports Amazon-fulfilled Prime claims, not your full launcher library.</p></div>`;
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

export function railEntries() {
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

export function buildRailItemHtml(p, selected) {
  const st = p.status || 'disconnected';
  const pillSt = displayStatus(st);
  const storeKey = connStoreKey(p);
  const sel = selected ? ' is-selected' : '';
  const unavailable = p.available === false;
  const unav = unavailable ? ' is-unavailable' : '';
  const title = unavailable
    ? `${p.label} is available on ${formatPlatformList(p.platforms)} only`
    : `Select ${p.label} to connect or manage`;

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

export function buildSteamRailBlock(p, selected) {
  const caption = (p.status === 'connected')
    ? ''
    : '<span class="conn-rail-rec-caption">Recommended first</span>';
  return `
    <div class="conn-rail-steam-wrap">
      ${caption}
      ${buildRailItemHtml(p, selected)}
    </div>`;
}

/** Build innerHTML for #connRail from collapsed rail entries. */
export function renderConnRailHtml(entries, selKey) {
  const railParts = [];
  const steam = entries.find(e => e.key === 'steam');
  if (steam) {
    railParts.push(buildSteamRailBlock(steam, selKey === steam.key));
  }
  for (const entry of entries) {
    if (entry.key === 'steam') continue;
    railParts.push(buildRailItemHtml(entry, selKey === entry.key));
  }
  return railParts.join('');
}

export function syncConnRailSelection(selKey) {
  document.querySelectorAll('#connRail .conn-rail-item[data-provider]').forEach(el => {
    const prov = el.getAttribute('data-provider');
    if (!prov) return;
    const selected = groupRepFor(prov) === selKey;
    el.classList.toggle('is-selected', selected);
    el.setAttribute('aria-selected', selected ? 'true' : 'false');
    el.tabIndex = selected ? 0 : -1;
  });
}
