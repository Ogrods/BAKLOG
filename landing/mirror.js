import { createClient } from './vendor/supabase-js.mjs';
import {
  STATUS_LABELS,
  STORE_LABELS,
  catalogArtifactPaths,
  filterMirrorRows,
  mergeItadPrices,
  mergeMirrorLibrary,
  sortMirrorRows,
  summarizeMirrorRows,
} from './mirror-merge.js';
import {
  MIRROR_ROW_HEIGHT_DESKTOP,
  MIRROR_ROW_HEIGHT_PHONE,
  computeMirrorVirtualRange,
  usesMirrorVirtualScroll,
} from './mirror-virtual.js';

const signInPanel = document.getElementById('mirrorSignInPanel');
const libraryPanel = document.getElementById('mirrorLibraryPanel');
const setupPanel = document.getElementById('mirrorSetupPanel');
const alertEl = document.getElementById('mirrorAlert');
const signInForm = document.getElementById('mirrorSignInForm');
const signInBtn = document.getElementById('mirrorSignInBtn');
const signedInActions = document.getElementById('mirrorSignedInActions');
const refreshBtn = document.getElementById('mirrorRefreshBtn');
const signOutBtn = document.getElementById('mirrorSignOutBtn');
const statsEl = document.getElementById('mirrorStats');
const mergeHintEl = document.getElementById('mirrorMergeHint');
const searchInput = document.getElementById('mirrorSearch');
const statusFilter = document.getElementById('mirrorStatusFilter');
const storeFilter = document.getElementById('mirrorStoreFilter');
const tableBody = document.getElementById('mirrorTableBody');
const emptyFiltered = document.getElementById('mirrorEmptyFiltered');
const lead = document.getElementById('mirrorLead');
const tableWrap = document.querySelector('.mirror-table-wrap');

const PHONE_MQ = '(max-width: 639.98px), (max-height: 480px) and (hover: none)';
const CATALOG_FETCH_CONCURRENCY = 5;
const COLSPAN = 10;

/** Retry header/Steam CDN once, then show letter placeholder. */
window.__baklogMirrorCoverError = function mirrorCoverError(img) {
  if (!img || img.dataset.mirrorCoverTried === '1') {
    img.style.display = 'none';
    const fallback = img.nextElementSibling;
    if (fallback) fallback.hidden = false;
    return;
  }
  const next = String(img.dataset.fallback || '').trim();
  if (next && /^https?:\/\//i.test(next) && next !== img.getAttribute('src')) {
    img.dataset.mirrorCoverTried = '1';
    img.src = next;
    return;
  }
  img.style.display = 'none';
  const fallback = img.nextElementSibling;
  if (fallback) fallback.hidden = false;
};

/** @type {ReturnType<typeof mergeMirrorLibrary>} */
let allRows = [];
/** @type {ReturnType<typeof mergeMirrorLibrary>} */
let filteredRows = [];
/** @type {import('@supabase/supabase-js').SupabaseClient | null} */
let supabase = null;

let _rowHeightPx = MIRROR_ROW_HEIGHT_DESKTOP;
let _virtualWindow = { start: 0, end: 0 };
let _virtualScrollRaf = 0;
let _virtualScrollBound = false;

function showAlert(message, { error = false } = {}) {
  if (!message) {
    alertEl.classList.add('hidden');
    alertEl.textContent = '';
    return;
  }
  alertEl.textContent = message;
  alertEl.classList.remove('hidden', 'mirror-alert--error', 'mirror-alert--info');
  alertEl.classList.add(error ? 'mirror-alert--error' : 'mirror-alert--info');
}

function showPanel(name) {
  signInPanel.classList.toggle('hidden', name !== 'signin');
  libraryPanel.classList.toggle('hidden', name !== 'library');
  setupPanel.classList.toggle('hidden', name !== 'setup');
  signedInActions.classList.toggle('hidden', name === 'signin');
}

/** @param {string[] | undefined} profiles */
function setMergeHint(profiles) {
  if (!mergeHintEl) return;
  const n = Array.isArray(profiles) ? profiles.filter(Boolean).length : 0;
  if (n > 1) {
    mergeHintEl.textContent = `Merged from ${n} cloud profiles.`;
    mergeHintEl.hidden = false;
    mergeHintEl.classList.remove('hidden');
  } else {
    mergeHintEl.textContent = '';
    mergeHintEl.hidden = true;
    mergeHintEl.classList.add('hidden');
  }
}

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function formatHours(value) {
  if (value == null || !Number.isFinite(Number(value))) return ' - ';
  const n = Number(value);
  return `${n % 1 === 0 ? n : n.toFixed(1)}h`;
}

function formatHltb(row) {
  const main = row.hltbMain;
  const extra = row.hltbExtra;
  if (main == null && extra == null) return ' - ';
  if (main != null && extra != null) {
    return `${formatHours(main).replace(/h$/, '')} / ${formatHours(extra)}`;
  }
  return formatHours(main ?? extra);
}

function formatPercent(value) {
  if (value == null || !Number.isFinite(Number(value))) return ' - ';
  return `${Math.round(Number(value))}%`;
}

function formatScore(value) {
  if (value == null || !Number.isFinite(Number(value))) return ' - ';
  return String(Math.round(Number(value)));
}

function coverCellHtml(row) {
  const initial = escapeHtml(String(row.title || '?').trim().charAt(0).toUpperCase() || '?');
  const url = String(row.coverUrl || '').trim();
  const fallback = String(row.coverFallbackUrl || '').trim();
  if (url && /^https?:\/\//i.test(url)) {
    const fbAttr =
      fallback && /^https?:\/\//i.test(fallback) && fallback !== url
        ? ` data-fallback="${escapeHtml(fallback)}"`
        : '';
    return `<td class="col-cover" data-label="Cover"><div class="mirror-cover-wrap"><img class="mirror-cover" src="${escapeHtml(url)}" alt="" loading="lazy" decoding="async"${fbAttr} onerror="window.__baklogMirrorCoverError&&window.__baklogMirrorCoverError(this)" /><span class="mirror-cover-fallback" hidden aria-hidden="true">${initial}</span></div></td>`;
  }
  return `<td class="col-cover" data-label="Cover"><div class="mirror-cover-wrap"><span class="mirror-cover-fallback" aria-hidden="true">${initial}</span></div></td>`;
}

function gameCellHtml(row) {
  const note = row.notes ? `<div class="mirror-note">${escapeHtml(row.notes)}</div>` : '';
  const metaBits = [];
  metaBits.push(`<span class="mirror-store-chip">${escapeHtml(row.storeLabel)}</span>`);
  if (Array.isArray(row.genres) && row.genres.length) {
    metaBits.push(`<span class="mirror-meta-text">${escapeHtml(row.genres.join(', '))}</span>`);
  }
  if (row.platforms) {
    metaBits.push(`<span class="mirror-meta-text">${escapeHtml(row.platforms)}</span>`);
  }
  return `<td class="col-game" data-label="Game"><div class="mirror-game-title">${escapeHtml(row.title)}</div>${note}<div class="mirror-row-meta">${metaBits.join('')}</div></td>`;
}

function rowHtml(row, index) {
  return `<tr data-row-index="${index}">
        ${coverCellHtml(row)}
        ${gameCellHtml(row)}
        <td data-label="Status"><span class="${statusClass(row.status)}">${escapeHtml(row.statusLabel)}</span></td>
        <td class="col-num" data-label="Played">${formatHours(row.playtimeHours)}</td>
        <td class="col-num" data-label="HLTB">${formatHltb(row)}</td>
        <td class="col-num col-steam" data-label="Steam %">${formatPercent(row.steamPercent)}</td>
        <td class="col-num col-mc" data-label="MC">${formatScore(row.metacritic)}</td>
        <td class="col-num col-price" data-label="Price">${escapeHtml(row.priceLabel || ' - ')}</td>
        <td class="col-date col-released" data-label="Released">${escapeHtml(row.released || ' - ')}</td>
        <td class="col-date col-lastplayed" data-label="Last played">${escapeHtml(row.lastPlayed || ' - ')}</td>
      </tr>`;
}

function statusClass(status) {
  if (status === 'playing') return 'mirror-status mirror-status--playing';
  if (status === 'finished') return 'mirror-status mirror-status--finished';
  if (status === 'next') return 'mirror-status mirror-status--next';
  return 'mirror-status';
}

function isPhoneLayout() {
  return typeof matchMedia === 'function' && matchMedia(PHONE_MQ).matches;
}

function estimateRowHeight() {
  return isPhoneLayout() ? MIRROR_ROW_HEIGHT_PHONE : MIRROR_ROW_HEIGHT_DESKTOP;
}

function refreshMeasuredRowHeight() {
  const row = tableBody?.querySelector('tr[data-row-index]');
  if (!row) return;
  const h = row.getBoundingClientRect().height;
  if (!(h > 0) || Math.abs(h - _rowHeightPx) < 0.5) return;
  _rowHeightPx = h;
}

const AUTH_CONFIG_CACHE_KEY = 'baklog-mirror-auth-config';

async function loadConfig() {
  try {
    const cached = sessionStorage.getItem(AUTH_CONFIG_CACHE_KEY);
    if (cached) {
      const parsed = JSON.parse(cached);
      if (parsed?.supabaseUrl && parsed?.supabaseAnonKey) return parsed;
    }
  } catch {
    // ignore cache parse / quota errors
  }
  const res = await fetch('/api/auth-config');
  if (res.status === 429) {
    throw new Error('Too many requests - wait about a minute, then refresh once.');
  }
  if (!res.ok) throw new Error('Auth not configured');
  const cfg = await res.json();
  try {
    sessionStorage.setItem(AUTH_CONFIG_CACHE_KEY, JSON.stringify(cfg));
  } catch {
    // ignore quota
  }
  return cfg;
}

async function mirrorFetch(path, token, profile) {
  const params = new URLSearchParams();
  if (path) params.set('path', path);
  if (profile) params.set('profile', profile);
  const qs = params.toString();
  const url = qs ? `/api/mirror?${qs}` : '/api/mirror';
  const res = await fetch(url, {
    headers: { Authorization: `Bearer ${token}` },
    cache: 'no-store',
  });
  let body = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  if (!res.ok) {
    const msg =
      res.status === 429
        ? 'Too many requests - wait about a minute, then refresh once.'
        : (body?.error || `Mirror request failed (${res.status})`);
    const err = new Error(msg);
    err.status = res.status;
    throw err;
  }
  return body;
}

/**
 * @template T
 * @param {T[]} items
 * @param {number} concurrency
 * @param {(item: T, index: number) => Promise<unknown>} worker
 */
async function mapPool(items, concurrency, worker) {
  const results = new Array(items.length);
  let next = 0;
  const limit = Math.max(1, Math.min(concurrency, items.length || 1));
  async function run() {
    while (next < items.length) {
      const i = next;
      next += 1;
      results[i] = await worker(items[i], i);
    }
  }
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, () => run()));
  return results;
}

function populateFilters(rows) {
  const summary = summarizeMirrorRows(rows);
  const currentStatus = statusFilter.value;
  const currentStore = storeFilter.value;

  statusFilter.innerHTML = '<option value="">All statuses</option>';
  for (const key of Object.keys(STATUS_LABELS)) {
    if (!summary.statuses[key]) continue;
    const opt = document.createElement('option');
    opt.value = key;
    opt.textContent = `${STATUS_LABELS[key]} (${summary.statuses[key]})`;
    statusFilter.appendChild(opt);
  }

  storeFilter.innerHTML = '<option value="">All stores</option>';
  for (const store of summary.stores) {
    const opt = document.createElement('option');
    opt.value = store;
    opt.textContent = STORE_LABELS[store] || store;
    storeFilter.appendChild(opt);
  }

  statusFilter.value = [...statusFilter.options].some((o) => o.value === currentStatus) ? currentStatus : '';
  storeFilter.value = [...storeFilter.options].some((o) => o.value === currentStore) ? currentStore : '';
}

function spacerHtml(kind, heightPx) {
  const h = Math.max(0, heightPx);
  return `<tr class="mirror-virtual-spacer mirror-virtual-spacer--${kind}" aria-hidden="true"><td colspan="${COLSPAN}" style="height:${h}px"></td></tr>`;
}

function tableTopY() {
  const el = tableWrap || tableBody?.closest('table');
  if (!el) return 0;
  return el.getBoundingClientRect().top + window.scrollY;
}

function ensureVirtualScrollBound() {
  if (_virtualScrollBound) return;
  _virtualScrollBound = true;
  const onScrollOrResize = () => {
    if (_virtualScrollRaf) return;
    _virtualScrollRaf = requestAnimationFrame(() => {
      _virtualScrollRaf = 0;
      if (!usesMirrorVirtualScroll(filteredRows.length)) return;
      paintMirrorSlice();
    });
  };
  window.addEventListener('scroll', onScrollOrResize, { passive: true });
  window.addEventListener('resize', onScrollOrResize, { passive: true });
}

function paintMirrorSlice() {
  const list = filteredRows;
  const len = list.length;
  if (!usesMirrorVirtualScroll(len)) {
    tableBody.innerHTML = list.map((row, i) => rowHtml(row, i)).join('');
    _virtualWindow = { start: 0, end: len };
    refreshMeasuredRowHeight();
    return;
  }

  ensureVirtualScrollBound();
  _rowHeightPx = _rowHeightPx || estimateRowHeight();
  const { start, end } = computeMirrorVirtualRange(len, {
    scrollY: window.scrollY,
    viewportH: window.innerHeight,
    rowHeight: _rowHeightPx,
    tableTop: tableTopY(),
  });

  if (start === _virtualWindow.start && end === _virtualWindow.end && tableBody.querySelector('tr[data-row-index]')) {
    return;
  }
  _virtualWindow = { start, end };

  const parts = [spacerHtml('top', start * _rowHeightPx)];
  for (let i = start; i < end; i += 1) {
    parts.push(rowHtml(list[i], i));
  }
  parts.push(spacerHtml('bottom', (len - end) * _rowHeightPx));
  tableBody.innerHTML = parts.join('');
  refreshMeasuredRowHeight();
}

function renderTable() {
  filteredRows = sortMirrorRows(
    filterMirrorRows(allRows, {
      search: searchInput.value,
      status: statusFilter.value,
      store: storeFilter.value,
    }),
    { column: 'title', direction: 'asc' },
  );

  const summary = summarizeMirrorRows(allRows);
  statsEl.innerHTML = `
    <span><strong>${summary.total}</strong> games mirrored</span>
    <span><strong>${summary.stores.length}</strong> store${summary.stores.length === 1 ? '' : 's'}</span>
    <span>Showing <strong>${filteredRows.length}</strong></span>
  `;

  _rowHeightPx = estimateRowHeight();
  _virtualWindow = { start: -1, end: -1 };
  paintMirrorSlice();

  emptyFiltered.classList.toggle('hidden', filteredRows.length > 0 || allRows.length === 0);
}

async function loadLibrary(session) {
  const token = session?.access_token;
  if (!token) return;
  const userId = String(session?.user?.id || '').trim();
  showAlert('');
  signInBtn.disabled = true;
  refreshBtn.disabled = true;
  try {
    const list = await mirrorFetch('', token);
    let catalogRows = (list.artifacts || []).filter((row) => catalogArtifactPaths([row]).length);
    const personalRows = (list.artifacts || []).filter((row) => row.path === 'data/personal.json');
    const itadRows = (list.artifacts || []).filter((row) => row.path === 'itad_prices.json');

    if (!catalogRows.length) {
      setMergeHint([]);
      lead.textContent = 'Signed in  -  waiting for your home PC to upload a mirror.';
      showPanel('setup');
      return;
    }

    catalogRows = [...catalogRows].sort((a, b) => {
      const rank = (row) => {
        const p = String(row.profile || '');
        if (userId && p === userId) return 0;
        if (p === 'default') return 1;
        return 2;
      };
      return rank(a) - rank(b);
    });

    const catalogs = await mapPool(catalogRows, CATALOG_FETCH_CONCURRENCY, async (row) => ({
      path: row.path,
      doc: await mirrorFetch(row.path, token, row.profile),
    }));
    let personal = null;
    let personalProfile = null;
    if (personalRows.length) {
      const pref =
        personalRows.find((row) => row.profile === userId)
        || personalRows.find((row) => row.profile === 'default')
        || personalRows[0];
      personalProfile = pref.profile;
      personal = await mirrorFetch('data/personal.json', token, pref.profile);
    }
    allRows = mergeMirrorLibrary(catalogs, personal);

    if (itadRows.length) {
      const itadPref =
        (personalProfile && itadRows.find((row) => row.profile === personalProfile))
        || itadRows.find((row) => row.profile === userId)
        || itadRows.find((row) => row.profile === 'default')
        || itadRows[0];
      try {
        const itadDoc = await mirrorFetch('itad_prices.json', token, itadPref.profile);
        allRows = mergeItadPrices(allRows, itadDoc);
      } catch {
        // Prices are optional enrichment.
      }
    }

    if (!allRows.length) {
      setMergeHint([]);
      lead.textContent = 'Signed in  -  mirror artifacts found but no playable rows yet.';
      showPanel('setup');
      return;
    }

    setMergeHint(list.profiles);
    populateFilters(allRows);
    lead.textContent = 'Read-only library from your synced home PC.';
    showPanel('library');
    renderTable();
  } finally {
    signInBtn.disabled = false;
    refreshBtn.disabled = false;
  }
}

async function ensureClient() {
  if (supabase) return supabase;
  const cfg = await loadConfig();
  supabase = createClient(cfg.supabaseUrl, cfg.supabaseAnonKey, {
    auth: {
      persistSession: true,
      autoRefreshToken: true,
      detectSessionInUrl: false,
    },
  });
  return supabase;
}

async function handleSignedIn(session) {
  const token = session?.access_token;
  if (!token) {
    showPanel('signin');
    return;
  }
  try {
    await loadLibrary(session);
  } catch (err) {
    if (err.status === 403) {
      showPanel('signin');
      showAlert('Pro sign-in required to view your cloud mirror.', { error: true });
      return;
    }
    showAlert(err.message || 'Could not load cloud mirror.', { error: true });
    showPanel('signin');
  }
}

async function boot() {
  try {
    const client = await ensureClient();
    const { data: { session } } = await client.auth.getSession();
    if (session) {
      await handleSignedIn(session);
      return;
    }
    showPanel('signin');
  } catch (err) {
    showPanel('signin');
    showAlert(err?.message || 'Cloud mirror sign-in is not available right now.', { error: true });
  }
}

signInForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  showAlert('');
  signInBtn.disabled = true;
  try {
    const client = await ensureClient();
    const email = document.getElementById('mirrorEmail').value.trim();
    const password = document.getElementById('mirrorPassword').value;
    const { data, error } = await client.auth.signInWithPassword({ email, password });
    if (error) {
      showAlert(error.message || 'Sign-in failed.', { error: true });
      return;
    }
    await handleSignedIn(data.session);
  } finally {
    signInBtn.disabled = false;
  }
});

refreshBtn.addEventListener('click', async () => {
  if (!supabase) return;
  const { data: { session } } = await supabase.auth.getSession();
  await handleSignedIn(session);
});

signOutBtn.addEventListener('click', async () => {
  if (supabase) await supabase.auth.signOut();
  allRows = [];
  filteredRows = [];
  tableBody.innerHTML = '';
  showAlert('');
  showPanel('signin');
  lead.textContent = 'Browse your cloud library from any browser.';
});

searchInput.addEventListener('input', renderTable);
statusFilter.addEventListener('change', renderTable);
storeFilter.addEventListener('change', renderTable);

/** Test hook for geometry audits (synthetic rows, no auth). */
window.__baklogMirrorTest = {
  setRows(rows) {
    allRows = Array.isArray(rows) ? rows : [];
    populateFilters(allRows);
    showPanel('library');
    lead.textContent = 'Test library';
    renderTable();
  },
  render() {
    renderTable();
  },
  getPaintedRowCount() {
    return tableBody.querySelectorAll('tr[data-row-index]').length;
  },
  getFilteredCount() {
    return filteredRows.length;
  },
  usesVirtual() {
    return usesMirrorVirtualScroll(filteredRows.length);
  },
};

boot();
