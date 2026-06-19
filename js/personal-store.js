import { baklogFetch, BAKLOG_LOCAL_HEADER, BAKLOG_LOCAL_HEADER_VALUE } from './api-client.js';
import { getAccessToken, isAccountAuthMode, isLocalProfilesEnabled } from './auth-gate.js';
import { state, STORAGE_KEY, MANUAL_KEY } from './state.js';
import { activeProfileId, libraryFirstSeenStorageKey, prefsStorageKey, profileScopedStorageKey } from './profiles.js';

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
  let profileSwitchSaveBlock = false;
  const PUSH_DEBOUNCE_MS = 600;

  function isProfileSwitchSaveBlocked() {
    return profileSwitchSaveBlock;
  }

  function snapshotLocal() {
    const snap = {
      personal: JSON.parse(JSON.stringify(state.personal || {})),
      prefs: JSON.parse(JSON.stringify(state.prefs || {})),
      manual: JSON.parse(JSON.stringify(getManualGamesFn())),
      libraryFirstSeen: JSON.parse(JSON.stringify(state.libraryFirstSeenByKey || {})),
    };
    // Claim the active profile so the server's 409 stale-profile guard fires.
    // In pure account-auth mode the JWT pins the profile, so the claim is omitted;
    // but with local profiles re-enabled the switcher is live and the claim matters.
    if (!isAccountAuthMode() || isLocalProfilesEnabled()) {
      snap.profile = activeProfileId();
    }
    return snap;
  }

  function isMeaningful(snap) {
    const personalKeys = Object.keys(snap.personal || {}).filter(k => k !== '__migrated_v3');
    if (personalKeys.length) return true;
    if ((snap.manual || []).length) return true;
    const seen = snap.libraryFirstSeen || {};
    if (Object.keys(seen).length) return true;
    return false;
  }

  function _loadCachedLibraryFirstSeen() {
    try {
      const raw = localStorage.getItem(libraryFirstSeenStorageKey());
      if (!raw) return {};
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === 'object' ? parsed : {};
    } catch {
      return {};
    }
  }

  async function probe() {
    if (apiAvailable !== null) return apiAvailable;
    try {
      const res = await baklogFetch('/api/personal', { method: 'GET' });
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
    // Server doc can lag behind loadPrefs()'s on-by-default migration; stale
    // rowHeroBackdrop:false must not undo the local toggle/migration each boot.
    'rowHeroBackdrop',
    'rowHeroBackdropDefaulted',
    // Local-only seed flag: a stale server copy must not re-arm the one-shot
    // first-seen seed, which would flood "Recently added" on the next boot.
    'librarySeenSeeded',
  ];

  // Merge first-seen maps. The server doc is normally authoritative, but a
  // stale/reset server map can carry `0` (placeholder seed) for a key the
  // local cache already stamped with a real timestamp. Never let a server `0`
  // (or non-numeric junk) clobber a real local timestamp.
  function _mergeFirstSeen(localSeen, serverSeen) {
    const out = { ...localSeen };
    for (const [key, sv] of Object.entries(serverSeen || {})) {
      const sn = Number(sv);
      const ln = Number(out[key]);
      if ((!Number.isFinite(sn) || sn <= 0) && Number.isFinite(ln) && ln > 0) continue;
      if (Number.isFinite(sn) && sn > 0 && Number.isFinite(ln) && ln > 0) {
        out[key] = sn >= ln ? sv : out[key];
        continue;
      }
      out[key] = sv;
    }
    return out;
  }

  function _nonBacklogCount(personalObj) {
    let n = 0;
    for (const [k, v] of Object.entries(personalObj || {})) {
      if (String(k).startsWith('__') || !v || typeof v !== 'object') continue;
      if ((v.status || 'backlog') !== 'backlog') n += 1;
    }
    return n;
  }

  function _dismissalEntryCount(personalObj) {
    const p = personalObj || {};
    const ids = (p.__dismissedClaims && typeof p.__dismissedClaims === 'object' && !Array.isArray(p.__dismissedClaims))
      ? p.__dismissedClaims
      : {};
    const keys = (p.__dismissedClaimKeys && typeof p.__dismissedClaimKeys === 'object' && !Array.isArray(p.__dismissedClaimKeys))
      ? p.__dismissedClaimKeys
      : {};
    return Object.keys(ids).length + Object.keys(keys).length;
  }

  function _isMeaningfulPersonalRecord(rec) {
    if (!rec || typeof rec !== 'object') return false;
    const st = rec.status || 'backlog';
    if (st !== 'backlog') return true;
    if (String(rec.notes || '').trim()) return true;
    if (rec.hltb_override != null && rec.hltb_override !== '') return true;
    if (rec.hidden === true) return true;
    if (rec.priority) return true;
    if (rec.exclude_from_count === true) return true;
    return false;
  }

  // Claim dismissals (__dismissedClaims / __dismissedClaimKeys) are timestamp
  // maps, not per-game records. A dismissal saved locally after the last
  // successful server PUT would be lost under the shallow "__ key, server wins"
  // rule, so the cleared claim reappears on the next reload. Union both sides
  // instead, keeping the newer numeric timestamp when a key exists on both
  // (non-numeric legacy values are preserved if that's all we have).
  const DISMISSAL_MAP_KEYS = new Set(['__dismissedClaims', '__dismissedClaimKeys', '__purgedClaimKeys']);

  function _mergeDismissalMaps(baseMap, incomingMap) {
    const base = baseMap && typeof baseMap === 'object' && !Array.isArray(baseMap) ? baseMap : {};
    const incoming = incomingMap && typeof incomingMap === 'object' && !Array.isArray(incomingMap) ? incomingMap : {};
    const out = { ...base };
    for (const [key, ts] of Object.entries(incoming)) {
      if (!(key in out)) { out[key] = ts; continue; }
      const a = Number(out[key]);
      const b = Number(ts);
      if (Number.isFinite(a) && Number.isFinite(b)) {
        if (b > a) out[key] = ts;
      } else if (!Number.isFinite(a) && Number.isFinite(b)) {
        out[key] = ts;
      }
    }
    return out;
  }

  function _mergePersonalPreferMeaningful(basePersonal, incomingPersonal) {
    const out = { ...(basePersonal || {}) };
    for (const [key, rec] of Object.entries(incomingPersonal || {})) {
      if (DISMISSAL_MAP_KEYS.has(key)) {
        out[key] = _mergeDismissalMaps(out[key], rec);
        continue;
      }
      if (String(key).startsWith('__')) {
        if (!(key in out)) out[key] = rec;
        continue;
      }
      if (!_isMeaningfulPersonalRecord(rec)) continue;
      const existing = out[key];
      if (!existing || typeof existing !== 'object') {
        out[key] = { ...rec };
        continue;
      }
      const existingSt = existing.status || 'backlog';
      const incomingSt = rec.status || 'backlog';
      const merged = { ...existing };
      if (existingSt === 'backlog' && incomingSt !== 'backlog') {
        merged.status = incomingSt;
        if (rec.started_at) merged.started_at = rec.started_at;
        if (rec.finished_at) merged.finished_at = rec.finished_at;
      }
      const existingNotes = String(existing.notes || '');
      const incomingNotes = String(rec.notes || '');
      if (incomingNotes.length > existingNotes.length) merged.notes = incomingNotes;
      if (rec.hltb_override != null && rec.hltb_override !== '' && merged.hltb_override == null) {
        merged.hltb_override = rec.hltb_override;
      }
      if (rec.hidden === true) merged.hidden = true;
      if (rec.exclude_from_count === true) merged.exclude_from_count = true;
      if (rec.exclude_from_count === false) merged.exclude_from_count = false;
      out[key] = merged;
    }
    return out;
  }

  function _loadLegacyUnscopedPersonal() {
    // Pre-multi-profile, personal lived at unscoped STORAGE_KEY (default's cache).
    // Default still reads/writes that key via personalStorageKey(); never merge it
    // into other profiles — that leaked default dismissals/personal into promo/test.
    return null;
  }

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
    merged.picksCollapsed = merged.picksCollapsed === true;
    state.prefs = merged;
    const localSeen = _loadCachedLibraryFirstSeen();
    const serverSeen = (doc.libraryFirstSeen && typeof doc.libraryFirstSeen === 'object')
      ? doc.libraryFirstSeen
      : {};
    state.libraryFirstSeenByKey = _mergeFirstSeen(localSeen, serverSeen);
    const manual = Array.isArray(doc.manual) ? doc.manual : [];
    localStorage.setItem(personalStorageKey(), JSON.stringify(state.personal));
    localStorage.setItem(prefsStorageKey(), JSON.stringify(state.prefs));
    localStorage.setItem(manualStorageKey(), JSON.stringify(manual));
    localStorage.setItem(
      libraryFirstSeenStorageKey(),
      JSON.stringify(state.libraryFirstSeenByKey),
    );
    setManualGamesFn(manual);
  }

  async function init() {
    profileSwitchSaveBlock = false;
    const localSnapBeforeProbe = snapshotLocal();
    const available = await probe();
    if (!available) return { migrated: false, pendingMigration: null };

    const serverHas = isMeaningful(serverDoc || {});
    const localHas = isMeaningful(localSnapBeforeProbe);
    const legacyPersonal = _loadLegacyUnscopedPersonal();

    if (serverHas) {
      let personal = serverDoc.personal || {};
      if (localHas) {
        personal = _mergePersonalPreferMeaningful(personal, localSnapBeforeProbe.personal);
      }
      if (legacyPersonal) {
        personal = _mergePersonalPreferMeaningful(personal, legacyPersonal);
      }
      const serverPersonal = serverDoc.personal || {};
      const serverDismissCount = _dismissalEntryCount(serverPersonal);
      const mergedDismissCount = _dismissalEntryCount(personal);
      const merged = _nonBacklogCount(personal) > _nonBacklogCount(serverPersonal);
      const dismissGrew = mergedDismissCount > serverDismissCount;
      applyServerDoc({ ...serverDoc, personal });
      initComplete = true;
      if (merged || dismissGrew) {
        dirty = true;
        clearTimeout(pushTimer);
        pushTimer = setTimeout(flush, PUSH_DEBOUNCE_MS);
      }
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
    if (profileSwitchSaveBlock) return;
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
        const res = await baklogFetch('/api/personal', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        if (!res.ok) {
          if (res.status === 409) {
            const detail = await res.text().catch(() => '');
            if (detail.includes('empty overwrite')) {
              console.warn('[personalStore] save rejected: refusing empty overwrite');
            } else {
              console.warn('[personalStore] save rejected: server active profile changed');
            }
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
    if (!initComplete) return;
    if (inFlight) {
      try { await inFlight; } catch (_) {}
    }
    if (!dirty) return;
    dirty = false;
    pushTimer = null;
    const snap = snapshotLocal();
    if (!isMeaningful(snap)) return;
    const ok = await putPayload(snap);
    if (!ok) dirty = true;
  }

  function flushSync() {
    if (profileSwitchSaveBlock) return;
    if (apiAvailable !== true) return;
    if (!initComplete) return;
    if (!dirty && !pushTimer) return;
    clearTimeout(pushTimer);
    pushTimer = null;
    dirty = false;
    const snap = snapshotLocal();
    if (!isMeaningful(snap)) return;
    const body = JSON.stringify(snap);
    try {
      const headers = {
        'Content-Type': 'application/json',
        [BAKLOG_LOCAL_HEADER]: BAKLOG_LOCAL_HEADER_VALUE,
      };
      if (isAccountAuthMode()) {
        const token = getAccessToken();
        if (token) headers.Authorization = `Bearer ${token}`;
      }
      fetch('/api/personal', { method: 'PUT', headers, body, keepalive: true }).catch((err) => {
        console.warn('[personalStore] keepalive flush failed', err);
      });
    } catch (err) {
      console.warn('[personalStore] unload flush failed', err);
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
    profileSwitchSaveBlock = true;
    try {
      const { cancelPendingPersonalSave } = await import('./personal-storage.js');
      cancelPendingPersonalSave();
    } catch (_) { /* ignore */ }
  }

  return {
    init,
    notify,
    flush,
    flushSync,
    prepareForProfileSwitch,
    uploadLocalToServer,
    dismissMigration,
    isProfileSwitchSaveBlocked,
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
        <span class="migration-banner-recommended">Recommended: syncing keeps your edits safe across browser refreshes and reinstalls.</span>
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
