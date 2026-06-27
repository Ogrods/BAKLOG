import { createClient } from './vendor/supabase-js.mjs';
import {
  STATUS_LABELS,
  STORE_LABELS,
  catalogArtifactPaths,
  filterMirrorRows,
  mergeMirrorLibrary,
  sortMirrorRows,
  summarizeMirrorRows,
} from './mirror-merge.js';

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
const searchInput = document.getElementById('mirrorSearch');
const statusFilter = document.getElementById('mirrorStatusFilter');
const storeFilter = document.getElementById('mirrorStoreFilter');
const tableBody = document.getElementById('mirrorTableBody');
const emptyFiltered = document.getElementById('mirrorEmptyFiltered');
const lead = document.getElementById('mirrorLead');

/** @type {ReturnType<typeof mergeMirrorLibrary>} */
let allRows = [];
/** @type {import('@supabase/supabase-js').SupabaseClient | null} */
let supabase = null;

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

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function formatHours(value) {
  if (value == null || !Number.isFinite(Number(value))) return '—';
  const n = Number(value);
  return `${n % 1 === 0 ? n : n.toFixed(1)}h`;
}

function statusClass(status) {
  if (status === 'playing') return 'mirror-status mirror-status--playing';
  if (status === 'finished') return 'mirror-status mirror-status--finished';
  if (status === 'next') return 'mirror-status mirror-status--next';
  return 'mirror-status';
}

async function loadConfig() {
  const res = await fetch('/api/auth-config');
  if (!res.ok) throw new Error('Auth not configured');
  return res.json();
}

async function mirrorFetch(path, token) {
  const url = path ? `/api/mirror?path=${encodeURIComponent(path)}` : '/api/mirror';
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
    const msg = body?.error || `Mirror request failed (${res.status})`;
    const err = new Error(msg);
    err.status = res.status;
    throw err;
  }
  return body;
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

function renderTable() {
  const filtered = sortMirrorRows(
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
    <span>Showing <strong>${filtered.length}</strong></span>
  `;

  tableBody.innerHTML = filtered
    .map((row) => {
      const note = row.notes ? `<div class="mirror-note">${escapeHtml(row.notes)}</div>` : '';
      return `<tr>
        <td>${escapeHtml(row.title)}${note}</td>
        <td>${escapeHtml(row.storeLabel)}</td>
        <td><span class="${statusClass(row.status)}">${escapeHtml(row.statusLabel)}</span></td>
        <td class="col-num">${formatHours(row.playtimeHours)}</td>
        <td class="col-num">${formatHours(row.hltbMain)}</td>
      </tr>`;
    })
    .join('');

  emptyFiltered.classList.toggle('hidden', filtered.length > 0 || allRows.length === 0);
}

async function loadLibrary(token) {
  showAlert('');
  signInBtn.disabled = true;
  refreshBtn.disabled = true;
  try {
    const list = await mirrorFetch('', token);
    const catalogPaths = catalogArtifactPaths(list.artifacts || []);
    const hasPersonal = (list.artifacts || []).some((row) => row.path === 'data/personal.json');

    if (!catalogPaths.length) {
      lead.textContent = 'Signed in — waiting for your home PC to upload a mirror.';
      showPanel('setup');
      return;
    }

    const catalogs = await Promise.all(
      catalogPaths.map(async (path) => ({ path, doc: await mirrorFetch(path, token) })),
    );
    const personal = hasPersonal ? await mirrorFetch('data/personal.json', token) : null;
    allRows = mergeMirrorLibrary(catalogs, personal);

    if (!allRows.length) {
      lead.textContent = 'Signed in — mirror artifacts found but no playable rows yet.';
      showPanel('setup');
      return;
    }

    populateFilters(allRows);
    lead.textContent = 'Read-only cloud library — edits stay on your home PC.';
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
    await loadLibrary(token);
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
  } catch {
    showPanel('signin');
    showAlert('Cloud mirror sign-in is not available right now.', { error: true });
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
  tableBody.innerHTML = '';
  showAlert('');
  showPanel('signin');
  lead.textContent = 'Browse your cloud library from any browser.';
});

searchInput.addEventListener('input', renderTable);
statusFilter.addEventListener('change', renderTable);
storeFilter.addEventListener('change', renderTable);

boot();
