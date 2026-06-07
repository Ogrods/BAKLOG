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
import { MANUAL_KEY, PREFS_KEY, STORAGE_KEY } from './state.js';
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

/** Base localStorage keys suffixed per profile (`:work`, etc.). Keep in sync with profileScopedStorageKey() callers. */
export const LS_FETCHER_AUTH_COOLDOWN = 'baklog-fetcher-auth-cooldown';
export const LS_RECONNECT_DISMISSED = 'baklog-reconnect-dismissed';
export const LS_ITAD_LAST_AUTO_RUN = 'baklog-itad-last-auto-run';
export const LS_AUTO_STALE_LAST_RUN = 'baklog-auto-stale-last-run';
export const LS_FETCHER_SUPPRESSED_RUNS = 'fetcher-suppressed-run-ids';
export const LS_FETCHER_LAST_SEQ = 'fetcher-last-seq-by-run';
export const LS_LIBRARY_WATCH = 'baklog-library-watch';

export const PROFILE_SCOPED_STORAGE_KEYS = Object.freeze([
  PREFS_KEY,
  ITAD_SNAPSHOT_PREFIX,
  STORAGE_KEY,
  MANUAL_KEY,
  LS_FETCHER_AUTH_COOLDOWN,
  LS_RECONNECT_DISMISSED,
  LS_ITAD_LAST_AUTO_RUN,
  LS_AUTO_STALE_LAST_RUN,
  LS_LIBRARY_WATCH,
]);

/** Profile-suffixed sessionStorage keys (fetcher SSE resume state). */
export const PROFILE_SCOPED_SESSION_KEYS = Object.freeze([
  LS_FETCHER_SUPPRESSED_RUNS,
  LS_FETCHER_LAST_SEQ,
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
  return localStorage.getItem(ACTIVE_PROFILE_LS) || _status?.active || 'default';
}

function profileKeySuffix(id) {
  const pid = id ?? activeProfileId();
  return pid && pid !== 'default' ? `:${pid}` : '';
}

export function prefsStorageKey() {
  return `${PREFS_KEY}${profileKeySuffix()}`;
}

export function itadSnapshotStorageKey() {
  return `${ITAD_SNAPSHOT_PREFIX}${profileKeySuffix()}`;
}

/** Prefix a localStorage base key with the active profile suffix. */
export function profileScopedStorageKey(base) {
  return `${base}${profileKeySuffix()}`;
}

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

function renderMenuList() {
  const list = el('profileMenuList');
  if (!list || !_status) return;
  const active = _status.active;
  const accountRow = isAccountAuthMode()
    ? `<div class="profile-menu-account-email px-3 py-2 text-xs text-slate-400 border-b border-slate-600/80">${escapeHtml(getAccountEmail() || 'Signed in')}</div>`
    : '';
  const rows = (_status.profiles || []).map((p) => {
    const selected = p.id === active;
    const lock = p.hasPin ? ' 🔒' : '';
    return `<button type="button" role="menuitem" class="profile-menu-option w-full text-left px-3 py-2 text-sm text-slate-200 hover:bg-slate-700/60 ${selected ? 'profile-menu-option-active' : ''}" data-profile-switch="${escapeAttr(p.id)}" data-profile-has-pin="${p.hasPin ? '1' : '0'}" title="Switch to this profile">${escapeHtml(p.label || p.id)}${lock}${selected ? ' ✓' : ''}</button>`;
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

async function switchProfile(id, pin) {
  closeMenu();
  const { personalStore } = await import('./personal-store.js');
  await personalStore.prepareForProfileSwitch();
  const body = { id };
  if (pin) body.pin = pin;
  await api('POST', '/api/profiles/active', body);
  localStorage.setItem(ACTIVE_PROFILE_LS, id);
  location.reload();
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
    await api('POST', '/api/profiles', { label });
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
  try {
    await api('DELETE', `/api/profiles/${encodeURIComponent(id)}`);
    clearProfileLocalStorage(id);
    await fetchProfilesStatus();
    populateDeleteSelect();
    if (sel) sel.value = '';
    setManageStatus(`Deleted “${label}”.`);
  } catch (e) {
    showManageError(e.message);
  }
}

function populateDeleteSelect() {
  const sel = el('profileDeleteSelect');
  if (!sel || !_status) return;
  const active = _status.active;
  const others = (_status.profiles || []).filter((p) => p.id !== active);
  sel.replaceChildren();
  const placeholder = document.createElement('option');
  placeholder.value = '';
  placeholder.textContent = others.length ? 'Select profile…' : 'No other profiles';
  sel.appendChild(placeholder);
  for (const p of others) {
    const opt = document.createElement('option');
    opt.value = p.id;
    opt.textContent = p.label || p.id;
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
        const go = (pin) => switchProfile(id, pin).catch((err) => alert(err.message));
        if (needPin) {
          const entered = window.prompt('Enter PIN for this profile:');
          if (entered != null && entered.trim()) go(entered.trim());
        } else {
          go();
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
