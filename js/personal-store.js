import { state, STORAGE_KEY, MANUAL_KEY } from './state.js';
import { activeProfileId, prefsStorageKey, profileScopedStorageKey } from './profiles.js';

function personalStorageKey() {
  return profileScopedStorageKey(STORAGE_KEY);
}

function manualStorageKey() {
  return profileScopedStorageKey(MANUAL_KEY);
}

let getManualGamesFn = () => [];
let setManualGamesFn = () => {};

export function configurePersonalStore({ getManualGames, setManualGames }) {
  getManualGamesFn = getManualGames;
  setManualGamesFn = setManualGames;
}

export const personalStore = (() => {
  let apiAvailable = null;
  let serverDoc = null;
  let pushTimer = null;
  let inFlight = null;
  let dirty = false;
  let initComplete = false;
  let pendingMigration = null;
  const PUSH_DEBOUNCE_MS = 600;

  function snapshotLocal() {
    return {
      profile: activeProfileId(),
      personal: JSON.parse(JSON.stringify(state.personal || {})),
      prefs: JSON.parse(JSON.stringify(state.prefs || {})),
      manual: JSON.parse(JSON.stringify(getManualGamesFn())),
      libraryFirstSeen: JSON.parse(JSON.stringify(state.libraryFirstSeenByKey || {})),
    };
  }

  function isMeaningful(snap) {
    const personalKeys = Object.keys(snap.personal || {}).filter(k => k !== '__migrated_v3');
    if (personalKeys.length) return true;
    if ((snap.manual || []).length) return true;
    return false;
  }

  async function probe() {
    if (apiAvailable !== null) return apiAvailable;
    try {
      const res = await fetch('/api/personal', { method: 'GET' });
      if (!res.ok) { apiAvailable = false; return false; }
      serverDoc = await res.json();
      apiAvailable = true;
      return true;
    } catch {
      apiAvailable = false;
      return false;
    }
  }

  // Preferences that describe the tab's current UI state. Server pushes get
  // debounced 600ms, so the server copy is often staler than what the user
  // just did in this tab — and reloading would otherwise snap them back.
  // Treat the local browser as authoritative for these.
  const LOCAL_FIRST_PREF_KEYS = [
    'activeView',
    'picksTab',
    'libraryPicksTab',
    'itchPicksTab',
    'picksCollapsed',
    'picksLimit',
    'viewSorts',
  ];

  function applyServerDoc(doc) {
    state.personal = doc.personal || {};
    const serverPrefs = doc.prefs || {};
    const localPrefs = state.prefs || {};
    const merged = { ...localPrefs, ...serverPrefs };
    for (const key of LOCAL_FIRST_PREF_KEYS) {
      if (Object.prototype.hasOwnProperty.call(localPrefs, key)) {
        merged[key] = localPrefs[key];
      }
    }
    state.prefs = merged;
    state.libraryFirstSeenByKey = (doc.libraryFirstSeen && typeof doc.libraryFirstSeen === 'object')
      ? doc.libraryFirstSeen
      : {};
    const manual = Array.isArray(doc.manual) ? doc.manual : [];
    localStorage.setItem(personalStorageKey(), JSON.stringify(state.personal));
    localStorage.setItem(prefsStorageKey(), JSON.stringify(state.prefs));
    localStorage.setItem(manualStorageKey(), JSON.stringify(manual));
    setManualGamesFn(manual);
  }

  async function init() {
    const localSnapBeforeProbe = snapshotLocal();
    const available = await probe();
    if (!available) return { migrated: false, pendingMigration: null };

    const serverHas = isMeaningful(serverDoc || {});
    const localHas = isMeaningful(localSnapBeforeProbe);

    if (serverHas) {
      applyServerDoc(serverDoc);
      initComplete = true;
      return { migrated: true, pendingMigration: null };
    }

    if (localHas) {
      pendingMigration = localSnapBeforeProbe;
      return { migrated: false, pendingMigration };
    }

    applyServerDoc(serverDoc || { personal: {}, prefs: {}, manual: [] });
    initComplete = true;
    return { migrated: true, pendingMigration: null };
  }

  async function uploadLocalToServer() {
    if (!pendingMigration) return false;
    const payload = pendingMigration;
    pendingMigration = null;
    initComplete = true;
    const ok = await putPayload(payload);
    if (ok && dirty) flush();
    return ok;
  }

  function dismissMigration() {
    pendingMigration = null;
    initComplete = true;
    if (dirty) flush();
  }

  function notify() {
    if (apiAvailable !== true) return;
    if (!initComplete) {
      dirty = true;
      return;
    }
    dirty = true;
    clearTimeout(pushTimer);
    pushTimer = setTimeout(flush, PUSH_DEBOUNCE_MS);
  }

  async function putPayload(payload) {
    inFlight = (async () => {
      try {
        const res = await fetch('/api/personal', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        if (!res.ok) {
          if (res.status === 409) {
            console.warn('[personalStore] save rejected: server active profile changed');
          } else {
            console.warn('[personalStore] PUT failed', res.status, await res.text().catch(() => ''));
          }
          return false;
        }
        serverDoc = await res.json();
        return true;
      } catch (err) {
        console.warn('[personalStore] PUT errored', err);
        return false;
      } finally {
        inFlight = null;
      }
    })();
    return inFlight;
  }

  async function flush() {
    if (apiAvailable !== true) return;
    if (inFlight) {
      try { await inFlight; } catch (_) {}
    }
    if (!dirty) return;
    dirty = false;
    pushTimer = null;
    const snap = snapshotLocal();
    const ok = await putPayload(snap);
    if (!ok) dirty = true;
  }

  function flushSync() {
    if (apiAvailable !== true) return;
    if (!dirty && !pushTimer) return;
    clearTimeout(pushTimer);
    pushTimer = null;
    dirty = false;
    const snap = snapshotLocal();
    try {
      const blob = new Blob([JSON.stringify(snap)], { type: 'application/json' });
      navigator.sendBeacon('/api/personal', blob);
    } catch (err) {
      console.warn('[personalStore] sendBeacon failed', err);
    }
  }

  /** Flush current profile to disk, then block further saves until reload (profile switch). */
  async function prepareForProfileSwitch() {
    clearTimeout(pushTimer);
    pushTimer = null;
    if (apiAvailable === true) {
      await flush();
    }
    dirty = false;
    initComplete = false;
  }

  return {
    init,
    notify,
    flush,
    flushSync,
    prepareForProfileSwitch,
    uploadLocalToServer,
    dismissMigration,
  };
})();

window.addEventListener('beforeunload', () => personalStore.flushSync());

export function showMigrationBanner(snap, { escapeHtml, onUploaded }) {
  const host = document.getElementById('migrationBanner');
  if (!host) return;
  const personalCount = Object.keys(snap.personal || {}).filter(k => k !== '__migrated_v3').length;
  const manualCount = (snap.manual || []).length;
  const parts = [];
  if (personalCount) parts.push(`${personalCount} personal edit${personalCount === 1 ? '' : 's'}`);
  if (manualCount) parts.push(`${manualCount} manual game${manualCount === 1 ? '' : 's'}`);
  const summary = parts.join(' + ') || 'your local data';
  host.innerHTML = `
    <div class="migration-banner-body">
      <div>
        <strong>Server file is empty.</strong>
        Found ${escapeHtml(summary)} in this browser that isn't on the server yet.
        Upload to <code class="bg-slate-700 px-1 rounded">data/personal.json</code>?
      </div>
      <div class="migration-banner-actions">
        <button type="button" id="migrationUpload" class="bg-emerald-700 hover:bg-emerald-600 px-3 py-1.5 rounded text-sm">Upload to server</button>
        <button type="button" id="migrationDismiss" class="bg-slate-700 hover:bg-slate-600 px-3 py-1.5 rounded text-sm">Dismiss</button>
      </div>
    </div>
  `;
  host.classList.remove('hidden');
  const close = () => {
    host.classList.add('hidden');
    host.innerHTML = '';
  };
  document.getElementById('migrationUpload').addEventListener('click', async () => {
    const btn = document.getElementById('migrationUpload');
    btn.disabled = true;
    btn.textContent = 'Uploading…';
    const ok = await personalStore.uploadLocalToServer();
    if (ok) {
      close();
      if (onUploaded) onUploaded();
    } else {
      btn.disabled = false;
      btn.textContent = 'Retry upload';
      const note = document.createElement('div');
      note.className = 'text-xs text-rose-300 mt-1';
      note.textContent = 'Upload failed. Check the server terminal for details.';
      host.querySelector('.migration-banner-body')?.appendChild(note);
    }
  });
  document.getElementById('migrationDismiss').addEventListener('click', () => {
    personalStore.dismissMigration();
    close();
  });
}
