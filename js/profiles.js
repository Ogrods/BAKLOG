/**
 * Local switchable profiles — header menu, manage modal, /api/profiles.
 * Switching active profile triggers a full page reload (no hot-swap).
 */

import { baklogFetch } from './api-client.js';
import {
  isAccountAuthMode,
  isLocalProfilesEnabled,
  getAccountEmail,
  getAccountProfileId,
  signOutAccount,
} from './auth-gate.js';
import {
  COLOR_THEME_KEY,
  KNOWN_LIBRARY_KEYS_KEY,
  LIBRARY_FIRST_SEEN_KEY,
  MANUAL_KEY,
  PREFS_KEY,
  STORAGE_KEY,
} from './state.js';
import { bindEscapeClose, trapFocus } from './focus-trap.js';
import { escapeAttr } from './dom-util.js';
import {
  getColorTheme,
  setColorTheme,
  THEMES,
  THEME_LABELS,
  THEME_SWATCHES,
  applyColorThemeFromStorage,
} from './theme.js';

export const ACTIVE_PROFILE_LS = 'baklog-active-profile';

const ITAD_SNAPSHOT_PREFIX = 'baklog-itad-snapshot';
const CLAIMS_SNAPSHOT_PREFIX = 'baklog-claims-snapshot';

/** Base localStorage keys suffixed per profile (`:work`, etc.). Keep in sync with profileScopedStorageKey() callers. */
export const LS_FETCHER_AUTH_COOLDOWN = 'baklog-fetcher-auth-cooldown';
export const LS_RECONNECT_DISMISSED = 'baklog-reconnect-dismissed';
export const LS_ITAD_LAST_AUTO_RUN = 'baklog-itad-last-auto-run';
export const LS_CLAIMS_LAST_AUTO_RUN = 'baklog-claims-last-auto-run';
export const LS_AUTO_STALE_LAST_RUN = 'baklog-auto-stale-last-run';
export const LS_FETCHER_SUPPRESSED_RUNS = 'fetcher-suppressed-run-ids';
export const LS_FETCHER_LAST_SEQ = 'fetcher-last-seq-by-run';
export const LS_LIBRARY_WATCH = 'baklog-library-watch';
export const LS_SPOTLIGHT_RECENT_KEYS = 'baklog-spotlight-recent';
export const LS_AD_CURSORS = 'baklog-ad-cursors';
export const LS_STAT_LAYOUT = 'baklog-fetcher-stat-layout';
export const LS_GALLERY_MODE = 'baklog.coverGalleryMode';
export const LS_DASH_FAILED_COVERS = 'baklog-dash-failed-covers';
export const LS_LANDSCAPE_COVERS = 'baklog-landscape-covers';
export const LS_METRICS_RENDERED = 'baklog-metrics-rendered';
export const LS_UNTAPPED_BATCH = 'baklog-metrics-untapped-batch-seeded';
/** Session-only; profile-suffixed like prefs. */
export const LS_ACTIVE_VIEW_SESSION = `${PREFS_KEY}:activeView`;
export const LS_METRIC_SEED = '__baklogMetricSeed';
export const LS_PRO_WELCOME = 'baklog-pro-welcome';

export const PROFILE_SCOPED_STORAGE_KEYS = Object.freeze([
  PREFS_KEY,
  ITAD_SNAPSHOT_PREFIX,
  CLAIMS_SNAPSHOT_PREFIX,
  STORAGE_KEY,
  MANUAL_KEY,
  LIBRARY_FIRST_SEEN_KEY,
  KNOWN_LIBRARY_KEYS_KEY,
  LS_SPOTLIGHT_RECENT_KEYS,
  LS_FETCHER_AUTH_COOLDOWN,
  LS_RECONNECT_DISMISSED,
  LS_ITAD_LAST_AUTO_RUN,
  LS_CLAIMS_LAST_AUTO_RUN,
  LS_AUTO_STALE_LAST_RUN,
  LS_LIBRARY_WATCH,
  LS_AD_CURSORS,
  COLOR_THEME_KEY,
  LS_STAT_LAYOUT,
  LS_GALLERY_MODE,
  LS_DASH_FAILED_COVERS,
  LS_LANDSCAPE_COVERS,
  LS_METRICS_RENDERED,
  LS_UNTAPPED_BATCH,
]);

/** Profile-suffixed sessionStorage keys (fetcher SSE resume state + active tab). */
export const PROFILE_SCOPED_SESSION_KEYS = Object.freeze([
  LS_ACTIVE_VIEW_SESSION,
  LS_FETCHER_SUPPRESSED_RUNS,
  LS_FETCHER_LAST_SEQ,
  LS_METRIC_SEED,
  LS_PRO_WELCOME,
]);

let _status = null;
let _menuOpen = false;
let _manageRelease = null;

function el(id) {
  return document.getElementById(id);
}

export function activeProfileId() {
  if (isAccountAuthMode() && !isLocalProfilesEnabled()) {
    const bound = getAccountProfileId();
    if (bound) return bound;
  }
  const stored = localStorage.getItem(ACTIVE_PROFILE_LS);
  if (stored) return stored;
  // Hybrid mode (Supabase + BAKLOG_LOCAL_PROFILES): auth-gate seeds the account
  // profile id before initProfiles() runs; use it instead of falling through to
  // 'default' while profiles/index.json already points at the account profile.
  if (isAccountAuthMode() && isLocalProfilesEnabled()) {
    const bound = getAccountProfileId();
    if (bound) return bound;
  }
  return _status?.active || 'default';
}

/**
 * Pin localStorage + _status to the server's active profile before personal
 * storage hydrates. Must run after initAuthGate() and before hydrateState().
 */
export async function ensureActiveProfileResolved() {
  if (isAccountAuthMode() && !isLocalProfilesEnabled()) {
    await syncAccountProfileId();
    return;
  }
  if (isAccountAuthMode() && isLocalProfilesEnabled()) {
    const bound = getAccountProfileId();
    if (bound && !localStorage.getItem(ACTIVE_PROFILE_LS)) {
      localStorage.setItem(ACTIVE_PROFILE_LS, bound);
    }
  }
  try {
    await fetchProfilesStatus();
  } catch {
    if (!_status?.active && !localStorage.getItem(ACTIVE_PROFILE_LS)) {
      const bound = getAccountProfileId();
      if (bound) localStorage.setItem(ACTIVE_PROFILE_LS, bound);
    }
  }
}

function profileKeySuffix(id) {
  const pid = id ?? activeProfileId();
  return pid && pid !== 'default' ? `:${pid}` : '';
}

export function prefsStorageKey() {
  return `${PREFS_KEY}${profileKeySuffix()}`;
}

// Active view lives in sessionStorage (not prefs/localStorage) so it survives a
// page refresh but resets to the default tab on a fresh session (app close +
// reopen). Profile-scoped like prefs so switching profiles doesn't leak views.
export function activeViewSessionKey(id) {
  return `${LS_ACTIVE_VIEW_SESSION}${profileKeySuffix(id)}`;
}

export function libraryFirstSeenStorageKey(id) {
  return `${LIBRARY_FIRST_SEEN_KEY}${profileKeySuffix(id)}`;
}

export function knownLibraryKeysStorageKey(id) {
  return `${KNOWN_LIBRARY_KEYS_KEY}${profileKeySuffix(id)}`;
}

export function spotlightRecentKeysStorageKey(id) {
  return `${LS_SPOTLIGHT_RECENT_KEYS}${profileKeySuffix(id)}`;
}

export function itadSnapshotStorageKey() {
  return `${ITAD_SNAPSHOT_PREFIX}${profileKeySuffix()}`;
}

export function claimsSnapshotStorageKey() {
  return `${CLAIMS_SNAPSHOT_PREFIX}${profileKeySuffix()}`;
}

export function colorThemeStorageKey(id) {
  return `${COLOR_THEME_KEY}${profileKeySuffix(id)}`;
}

export function statLayoutStorageKey(id) {
  return `${LS_STAT_LAYOUT}${profileKeySuffix(id)}`;
}

export function galleryModeStorageKey(id) {
  return `${LS_GALLERY_MODE}${profileKeySuffix(id)}`;
}

export function dashFailedCoversStorageKey(id) {
  return `${LS_DASH_FAILED_COVERS}${profileKeySuffix(id)}`;
}

export function landscapeCoversStorageKey(id) {
  return `${LS_LANDSCAPE_COVERS}${profileKeySuffix(id)}`;
}

export function metricsRenderedStorageKey(id) {
  return `${LS_METRICS_RENDERED}${profileKeySuffix(id)}`;
}

export function untappedBatchMarkerStorageKey(id) {
  return `${LS_UNTAPPED_BATCH}${profileKeySuffix(id)}`;
}

export function metricSeedSessionKey(id) {
  return `${LS_METRIC_SEED}${profileKeySuffix(id)}`;
}

export function proWelcomeSessionKey(id) {
  return `${LS_PRO_WELCOME}${profileKeySuffix(id)}`;
}

/** Prefix a localStorage base key with the active profile suffix. */
export function profileScopedStorageKey(base) {
  return `${base}${profileKeySuffix()}`;
}

/** Wipe per-profile browser caches (localStorage + sessionStorage suffixes). */
export function clearProfileLocalStorage(profileId) {
  try {
    const suffix = profileId && profileId !== 'default' ? `:${profileId}` : '';
    if (!suffix) return;
    for (const base of PROFILE_SCOPED_STORAGE_KEYS) {
      localStorage.removeItem(`${base}${suffix}`);
    }
    for (const base of PROFILE_SCOPED_SESSION_KEYS) {
      sessionStorage.removeItem(`${base}${suffix}`);
    }
  } catch (_) { /* ignore */ }
}

/** Alias for delete/create paths that must not reuse stale client caches. */
export const resetProfileClientCache = clearProfileLocalStorage;

function syncActiveToStorage() {
  if (_status?.active) {
    localStorage.setItem(ACTIVE_PROFILE_LS, _status.active);
  }
}

async function api(method, path, body) {
  const opts = { method, headers: {} };
  if (body != null) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const res = await baklogFetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const msg = data?.error || res.statusText || 'Request failed';
    throw new Error(msg);
  }
  return data;
}

export async function fetchProfilesStatus() {
  _status = await api('GET', '/api/profiles');
  syncActiveToStorage();
  renderProfileTrigger();
  return _status;
}

function renderProfileTrigger() {
  const label = el('profileMenuLabel');
  const trigger = el('profileMenuTrigger');
  if (!label || !trigger) return;
  const name = _status?.active_label || 'Default';
  label.textContent = name;
  label.title = name;
  trigger.setAttribute('aria-label', `Profile: ${name}`);
}

function closeMenu() {
  _menuOpen = false;
  const menu = el('profileMenu');
  const trigger = el('profileMenuTrigger');
  if (menu) menu.hidden = true;
  if (trigger) trigger.setAttribute('aria-expanded', 'false');
}

function openMenu() {
  _menuOpen = true;
  const menu = el('profileMenu');
  const trigger = el('profileMenuTrigger');
  if (!menu || !trigger) return;
  renderMenuList();
  renderThemeList();
  menu.hidden = false;
  trigger.setAttribute('aria-expanded', 'true');
}

function setThemeNameLabel(text) {
  const n = el('profileThemeName');
  if (n) n.textContent = text;
}

let _themeSwatchHoverWired = false;

function wireThemeSwatchHover(list) {
  if (!list || _themeSwatchHoverWired) return;
  _themeSwatchHoverWired = true;
  list.addEventListener('pointerover', (e) => {
    const b = e.target.closest('[data-theme-set]');
    if (b) setThemeNameLabel(THEME_LABELS[b.dataset.themeSet] || b.dataset.themeSet);
  });
  list.addEventListener('pointerleave', () => {
    const active = getColorTheme();
    setThemeNameLabel(THEME_LABELS[active] || active);
  });
}

function renderThemeList() {
  const list = el('profileThemeList');
  if (!list) return;
  const active = getColorTheme();
  list.innerHTML = THEMES.map((id) => {
    const sw = THEME_SWATCHES[id] || {};
    const name = THEME_LABELS[id] || id;
    const grad = `linear-gradient(135deg, ${sw.bg} 0%, ${sw.bg} 55%, ${sw.accent} 90%, ${sw.accent2} 100%)`;
    const selected = id === active;
    return `<button type="button" role="menuitemradio" aria-checked="${selected}" class="theme-swatch${selected ? ' is-active' : ''}" data-theme-set="${escapeAttr(id)}" title="${escapeAttr(name)}" aria-label="${escapeAttr(name)}" style="--swatch-grad:${grad}; --swatch-accent:${sw.accent || '#fff'}"></button>`;
  }).join('');
  setThemeNameLabel(THEME_LABELS[active] || active);
  wireThemeSwatchHover(list);
}

function handleMenuThemeClick(e) {
  const btn = e.target.closest('[data-theme-set]');
  if (!btn) return false;
  // renderThemeList() below replaces the swatch element we just clicked, which
  // detaches e.target. The document-level "click outside" handler would then
  // fail its e.target.closest('#profileMenuWrap') check and close the menu.
  // Stop propagation so theme previews keep the menu open.
  e.stopPropagation();
  const id = btn.getAttribute('data-theme-set');
  if (id) {
    setColorTheme(id);
    renderThemeList();
  }
  return true;
}

/**
 * Display label for a profile. Labels aren't unique (two profiles can both be
 * "Work"); when a label collides with another profile's, append the id so the
 * rows are distinguishable, e.g. "Work (work-2)". Comparison is trimmed +
 * case-insensitive so "Work" and "work " count as a collision.
 */
export function profileDisplayLabel(profile, profiles) {
  const label = (profile?.label || profile?.id || '').toString();
  const norm = label.trim().toLowerCase();
  const collides = (profiles || []).some(
    (other) =>
      other !== profile &&
      other?.id !== profile?.id &&
      ((other?.label || other?.id || '').toString().trim().toLowerCase() === norm),
  );
  return collides ? `${label} (${profile?.id})` : label;
}

function renderMenuList() {
  const list = el('profileMenuList');
  if (!list || !_status) return;
  const active = _status.active;
  const profiles = _status.profiles || [];
  const accountRow = isAccountAuthMode()
    ? `<div class="profile-menu-account-email px-3 py-2 text-xs text-slate-400 border-b border-slate-600/80">${escapeHtml(getAccountEmail() || 'Signed in')}</div>`
    : '';
  const rows = profiles.map((p) => {
    const selected = p.id === active;
    const lock = p.hasPin ? ' 🔒' : '';
    return `<button type="button" role="menuitem" class="profile-menu-option w-full text-left px-3 py-2 text-sm text-slate-200 hover:bg-slate-700/60 ${selected ? 'profile-menu-option-active' : ''}" data-profile-switch="${escapeAttr(p.id)}" data-profile-has-pin="${p.hasPin ? '1' : '0'}" title="Switch to this profile">${escapeHtml(profileDisplayLabel(p, profiles))}${lock}${selected ? ' ✓' : ''}</button>`;
  });
  const signOutRow = isAccountAuthMode()
    ? `<button type="button" role="menuitem" class="profile-menu-option w-full text-left px-3 py-2 text-sm text-slate-200 hover:bg-slate-700/60 border-t border-slate-600/80" data-account-signout title="Sign out of this account">Sign out</button>`
    : '';
  list.innerHTML = accountRow + rows.join('') + signOutRow;
  const footer = document.querySelector('#profileMenu [data-profile-manage]');
  if (footer) footer.classList.remove('hidden');
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/**
 * Forget the target profile's last-open tab so switching always lands on the
 * dashboard instead of restoring whatever view that profile was left on.
 */
function resetTabMemoryForProfile(id) {
  try {
    // Active view now lives in sessionStorage; clear it so the switched-in
    // profile reloads onto the dashboard rather than a view it was left on
    // earlier this session.
    sessionStorage.removeItem(activeViewSessionKey(id));
    const suffix = id && id !== 'default' ? `:${id}` : '';
    // Scrub any stale activeView left in legacy localStorage prefs (pre-session
    // migration) so it can't leak back if read elsewhere.
    const key = `${PREFS_KEY}${suffix}`;
    const raw = localStorage.getItem(key);
    if (!raw) return;
    const prefs = JSON.parse(raw);
    if (prefs && 'activeView' in prefs) {
      delete prefs.activeView;
      localStorage.setItem(key, JSON.stringify(prefs));
    }
  } catch (_) { /* ignore */ }
}

async function switchProfile(id, pin) {
  closeMenu();
  const { personalStore } = await import('./personal-store.js');
  await personalStore.prepareForProfileSwitch();
  const body = { id };
  if (pin) body.pin = pin;
  await api('POST', '/api/profiles/active', body);
  localStorage.setItem(ACTIVE_PROFILE_LS, id);
  resetTabMemoryForProfile(id);
  location.reload();
}

/** Map server PIN error tokens to friendly copy; pass through human strings. */
export function friendlyPinError(msg) {
  const raw = String(msg || '').trim();
  if (raw === 'incorrect_pin') return 'Incorrect PIN. Try again.';
  if (raw === 'pin_required') return 'Enter the PIN for this profile.';
  // The 429 lockout message is already human-readable; normalize any em dash.
  return raw.replace(/\s*\u2014\s*/g, ' - ') || 'Could not switch profile.';
}

let _pinPromptTarget = null;
let _pinPromptRelease = null;
let _pinPromptOnSubmit = null;

function setPinPromptError(msg) {
  const errEl = el('profilePinPromptError');
  if (!errEl) return;
  if (msg) {
    errEl.textContent = msg;
    errEl.classList.remove('hidden');
  } else {
    errEl.textContent = '';
    errEl.classList.add('hidden');
  }
}

/**
 * Open the masked PIN dialog. Defaults to switching into `id`; pass
 * `opts.onSubmit(id, pin)` (and optional note/submitLabel) to reuse the dialog
 * for other locked actions such as deleting a PIN-protected profile.
 */
function openPinPrompt(id, opts = {}) {
  closeMenu();
  _pinPromptTarget = id;
  _pinPromptOnSubmit = typeof opts.onSubmit === 'function'
    ? opts.onSubmit
    : (pid, pin) => switchProfile(pid, pin);
  const modal = el('profilePinModal');
  if (!modal) return;
  const dialog = modal.querySelector('[role="dialog"]') || modal;
  const input = el('profilePinPromptInput');
  const note = el('profilePinPromptNote');
  const submitBtn = el('profilePinPromptSubmit');
  const profiles = _status?.profiles || [];
  const target = profiles.find((p) => p.id === id);
  const name = target ? profileDisplayLabel(target, profiles) : id;
  if (note) {
    note.textContent = opts.note || `“${name}” is locked. Enter its PIN to switch in.`;
  }
  if (submitBtn) submitBtn.textContent = opts.submitLabel || 'Switch';
  if (input) input.value = '';
  setPinPromptError('');
  modal.classList.remove('hidden');
  modal.classList.add('flex');
  _pinPromptRelease = trapFocus(dialog, { onEscape: closePinPrompt });
  input?.focus();
}

function closePinPrompt() {
  const modal = el('profilePinModal');
  if (!modal) return;
  modal.classList.add('hidden');
  modal.classList.remove('flex');
  _pinPromptRelease?.();
  _pinPromptRelease = null;
  _pinPromptTarget = null;
  _pinPromptOnSubmit = null;
  el('profileMenuTrigger')?.focus();
}

async function submitPinPrompt() {
  const id = _pinPromptTarget;
  const onSubmit = _pinPromptOnSubmit;
  if (!id || !onSubmit) return;
  const pin = (el('profilePinPromptInput')?.value || '').trim();
  if (!pin) {
    setPinPromptError('Enter the PIN for this profile.');
    return;
  }
  const submitBtn = el('profilePinPromptSubmit');
  if (submitBtn) submitBtn.disabled = true;
  try {
    await onSubmit(id, pin);
    closePinPrompt();
  } catch (err) {
    setPinPromptError(friendlyPinError(err.message));
    const input = el('profilePinPromptInput');
    if (input) {
      input.value = '';
      input.focus();
    }
  } finally {
    if (submitBtn) submitBtn.disabled = false;
  }
}

function clearManageMessages() {
  const errEl = el('profileManageError');
  const statusEl = el('profileManageStatus');
  if (errEl) {
    errEl.textContent = '';
    errEl.classList.add('hidden');
  }
  if (statusEl) {
    statusEl.textContent = '';
    statusEl.classList.add('hidden');
  }
}

function setManageStatus(msg) {
  const statusEl = el('profileManageStatus');
  const errEl = el('profileManageError');
  if (errEl) {
    errEl.textContent = '';
    errEl.classList.add('hidden');
  }
  if (statusEl) {
    statusEl.textContent = msg;
    statusEl.classList.remove('hidden');
  }
}

function showManageError(msg) {
  const errEl = el('profileManageError');
  const statusEl = el('profileManageStatus');
  if (statusEl) {
    statusEl.textContent = '';
    statusEl.classList.add('hidden');
  }
  if (errEl) {
    errEl.textContent = msg;
    errEl.classList.remove('hidden');
  }
}

function openManageModal() {
  closeMenu();
  const modal = el('profileManageModal');
  if (!modal) return;
  const dialog = modal.querySelector('[role="dialog"]') || modal;
  modal.classList.remove('hidden');
  modal.classList.add('flex');
  const renameInput = el('profileRenameInput');
  if (renameInput && _status) {
    renameInput.value = _status.active_label || '';
  }
  clearManageMessages();
  _manageRelease = trapFocus(dialog, { onEscape: closeManageModal });
  el('profileRenameInput')?.focus();
}

function closeManageModal() {
  const modal = el('profileManageModal');
  if (!modal) return;
  modal.classList.add('hidden');
  modal.classList.remove('flex');
  _manageRelease?.();
  _manageRelease = null;
  el('profileMenuTrigger')?.focus();
}

async function createProfile() {
  const input = el('profileNewName');
  const label = (input?.value || '').trim();
  if (!label) {
    showManageError('Enter a name for the new profile.');
    return;
  }
  try {
    const created = await api('POST', '/api/profiles', { label });
    resetProfileClientCache(created?.id || '');
    if (input) input.value = '';
    await fetchProfilesStatus();
    populateDeleteSelect();
    setManageStatus(`Created “${label}”.`);
  } catch (e) {
    showManageError(e.message);
  }
}

async function renameActiveProfile() {
  const input = el('profileRenameInput');
  const label = (input?.value || '').trim();
  if (!label || !_status?.active) return;
  try {
    await api('PUT', `/api/profiles/${encodeURIComponent(_status.active)}`, { label });
    await fetchProfilesStatus();
    if (input) input.value = _status.active_label || label;
    setManageStatus(`Renamed to “${label}”.`);
  } catch (e) {
    showManageError(e.message);
  }
}

async function performProfileDelete(id, pin, label) {
  await api('DELETE', `/api/profiles/${encodeURIComponent(id)}`, pin ? { currentPin: pin } : undefined);
  resetProfileClientCache(id);
  await fetchProfilesStatus();
  populateDeleteSelect();
  const sel = el('profileDeleteSelect');
  if (sel) sel.value = '';
  setManageStatus(`Deleted “${label}”.`);
}

async function deleteSelectedProfile() {
  const sel = el('profileDeleteSelect');
  const id = sel?.value;
  if (!id) return;
  if (id === _status?.active) {
    showManageError('Switch to another profile before deleting this one.');
    return;
  }
  const label = sel.selectedOptions[0]?.textContent || id;
  if (!confirm(`Delete profile "${label}"? This removes its games and connections under profiles/${id}/. Root backup files are not deleted.`)) {
    return;
  }
  // A PIN-locked profile requires its PIN to delete, mirroring switch-in.
  const target = (_status?.profiles || []).find((p) => p.id === id);
  if (target?.hasPin) {
    openPinPrompt(id, {
      note: `“${label}” is locked. Enter its PIN to delete it.`,
      submitLabel: 'Delete',
      onSubmit: (pid, pin) => performProfileDelete(pid, pin, label),
    });
    return;
  }
  try {
    await performProfileDelete(id, '', label);
  } catch (e) {
    showManageError(e.message);
  }
}

function populateDeleteSelect() {
  const sel = el('profileDeleteSelect');
  if (!sel || !_status) return;
  const active = _status.active;
  const profiles = _status.profiles || [];
  const others = profiles.filter((p) => p.id !== active);
  sel.replaceChildren();
  const placeholder = document.createElement('option');
  placeholder.value = '';
  placeholder.textContent = others.length ? 'Select profile…' : 'No other profiles';
  sel.appendChild(placeholder);
  for (const p of others) {
    const opt = document.createElement('option');
    opt.value = p.id;
    opt.textContent = profileDisplayLabel(p, profiles);
    sel.appendChild(opt);
  }
}

export function bindProfilesUI() {
  const trigger = el('profileMenuTrigger');
  const menu = el('profileMenu');
  if (!trigger || !menu) return;

  trigger.addEventListener('click', (e) => {
    e.stopPropagation();
    // Boot curtain blocks pointer events via CSS; guard keyboard activation too
    // so the profile menu can't open (and switch/reload) mid-boot.
    if (document.documentElement.hasAttribute('data-boot-loading')) return;
    if (_menuOpen) closeMenu();
    else openMenu();
  });

  menu.addEventListener('click', (e) => {
    if (handleMenuThemeClick(e)) return;
    if (e.target.closest('[data-account-signout]')) {
      closeMenu();
      signOutAccount({ intentional: true }).finally(() => location.reload());
      return;
    }
    const sw = e.target.closest('[data-profile-switch]');
    if (sw) {
      const id = sw.getAttribute('data-profile-switch');
      if (id && id !== _status?.active) {
        const needPin = sw.getAttribute('data-profile-has-pin') === '1';
        if (needPin) {
          openPinPrompt(id);
        } else {
          switchProfile(id).catch((err) => alert(friendlyPinError(err.message)));
        }
      }
      return;
    }
    if (e.target.closest('[data-profile-manage]')) {
      populateDeleteSelect();
      syncPinManageFields();
      openManageModal();
    }
  });

  document.addEventListener('click', (e) => {
    if (!_menuOpen) return;
    if (e.target.closest('#profileMenuWrap')) return;
    closeMenu();
  });

  el('profileManageClose')?.addEventListener('click', closeManageModal);
  el('profileManageCancel')?.addEventListener('click', closeManageModal);
  el('profilePinPromptClose')?.addEventListener('click', closePinPrompt);
  el('profilePinPromptCancel')?.addEventListener('click', closePinPrompt);
  el('profilePinPromptSubmit')?.addEventListener('click', () => submitPinPrompt());
  el('profilePinPromptInput')?.addEventListener('input', () => setPinPromptError(''));
  el('profilePinPromptInput')?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      submitPinPrompt();
    }
  });
  bindEscapeClose(el('profilePinModal'), closePinPrompt);
  el('profileRenameSave')?.addEventListener('click', () => renameActiveProfile());
  el('profileCreateBtn')?.addEventListener('click', () => createProfile());
  el('profileDeleteBtn')?.addEventListener('click', () => deleteSelectedProfile());
  el('profilePinSave')?.addEventListener('click', () => saveProfilePin());
  el('profilePinClear')?.addEventListener('click', () => clearProfilePin());

  for (const id of ['profileRenameInput', 'profileNewName', 'profileDeleteSelect', 'profilePinNew', 'profilePinCurrent']) {
    el(id)?.addEventListener('input', clearManageMessages);
    el(id)?.addEventListener('change', clearManageMessages);
  }

  bindEscapeClose(el('profileManageModal'), closeManageModal);
}

/**
 * Account-mode header menu: shows the signed-in email + Sign out.
 * Profile switching stays disabled (the profile is bound to the Supabase user).
 */
function renderAccountMenu(email) {
  const label = el('profileMenuLabel');
  const trigger = el('profileMenuTrigger');
  const shown = email || 'Account';
  if (label) {
    label.textContent = shown;
    label.title = shown;
  }
  if (trigger) trigger.setAttribute('aria-label', email ? `Account: ${email}` : 'Account');
  const list = el('profileMenuList');
  if (list) {
    list.innerHTML =
      `<div class="profile-menu-account-email px-3 py-2 text-xs text-slate-400 border-b border-slate-600/80">${escapeHtml(email || 'Signed in')}</div>` +
      `<button type="button" role="menuitem" class="profile-menu-option w-full text-left px-3 py-2 text-sm text-slate-200 hover:bg-slate-700/60" data-account-signout title="Sign out of this account">Sign out</button>`;
  }
  const footer = document.querySelector('#profileMenu [data-profile-manage]');
  if (footer) footer.classList.add('hidden');
}

function bindAccountMenu() {
  const trigger = el('profileMenuTrigger');
  const menu = el('profileMenu');
  if (!trigger || !menu) return;

  trigger.addEventListener('click', (e) => {
    e.stopPropagation();
    if (document.documentElement.hasAttribute('data-boot-loading')) return;
    if (_menuOpen) {
      closeMenu();
    } else {
      renderThemeList();
      menu.hidden = false;
      _menuOpen = true;
      trigger.setAttribute('aria-expanded', 'true');
    }
  });

  menu.addEventListener('click', async (e) => {
    if (handleMenuThemeClick(e)) return;
    if (!e.target.closest('[data-account-signout]')) return;
    closeMenu();
    try {
      await signOutAccount({ intentional: true });
    } finally {
      location.reload();
    }
  });

  document.addEventListener('click', (e) => {
    if (!_menuOpen) return;
    if (e.target.closest('#profileMenuWrap')) return;
    closeMenu();
  });
}

async function syncAccountProfileId() {
  try {
    const res = await baklogFetch('/api/auth/session');
    if (!res.ok) return;
    const data = await res.json();
    if (data.profile) {
      localStorage.setItem(ACTIVE_PROFILE_LS, data.profile);
    }
  } catch (_) { /* ignore */ }
}

function syncPinManageFields() {
  const active = (_status?.profiles || []).find((p) => p.id === _status?.active);
  const hasPin = !!active?.hasPin;
  const currentWrap = el('profilePinCurrentWrap');
  const clearBtn = el('profilePinClear');
  const note = el('profilePinNote');
  if (currentWrap) currentWrap.classList.toggle('hidden', !hasPin);
  if (clearBtn) clearBtn.classList.toggle('hidden', !hasPin);
  if (note) {
    note.textContent = hasPin
      ? 'This profile requires a PIN to switch into it from another profile.'
      : 'Optional - lock this profile so switching in requires a PIN.';
  }
}

async function saveProfilePin() {
  if (!_status?.active) return;
  const pin = (el('profilePinNew')?.value || '').trim();
  const current = (el('profilePinCurrent')?.value || '').trim();
  if (!pin) {
    showManageError('Enter a new PIN.');
    return;
  }
  try {
    const body = { pin };
    if (current) body.currentPin = current;
    await api('POST', `/api/profiles/${encodeURIComponent(_status.active)}/pin`, body);
    if (el('profilePinNew')) el('profilePinNew').value = '';
    if (el('profilePinCurrent')) el('profilePinCurrent').value = '';
    await fetchProfilesStatus();
    syncPinManageFields();
    setManageStatus('PIN saved.');
  } catch (e) {
    showManageError(e.message);
  }
}

async function clearProfilePin() {
  if (!_status?.active) return;
  const current = (el('profilePinCurrent')?.value || '').trim();
  if (!current) {
    showManageError('Enter the current PIN to remove it.');
    return;
  }
  try {
    await api('DELETE', `/api/profiles/${encodeURIComponent(_status.active)}/pin`, { currentPin: current });
    if (el('profilePinCurrent')) el('profilePinCurrent').value = '';
    if (el('profilePinNew')) el('profilePinNew').value = '';
    await fetchProfilesStatus();
    syncPinManageFields();
    setManageStatus('PIN removed.');
  } catch (e) {
    showManageError(e.message);
  }
}

export async function initProfiles() {
  applyColorThemeFromStorage();
  renderThemeList();
  const wrap = el('profileMenuWrap');
  if (isAccountAuthMode() && !isLocalProfilesEnabled()) {
    if (wrap) wrap.classList.remove('hidden');
    await syncAccountProfileId();
    renderAccountMenu(getAccountEmail());
    bindAccountMenu();
    return;
  }
  if (wrap) wrap.classList.remove('hidden');
  const seeded = localStorage.getItem(ACTIVE_PROFILE_LS);
  if (seeded) renderProfileTrigger();
  try {
    await fetchProfilesStatus();
  } catch {
    if (!seeded) {
      const label = el('profileMenuLabel');
      if (label) label.textContent = 'Default';
    }
  }
  bindProfilesUI();
}
