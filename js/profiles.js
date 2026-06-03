/**
 * Local switchable profiles — header menu, manage modal, /api/profiles.
 * Switching active profile triggers a full page reload (no hot-swap).
 */

import { PREFS_KEY } from './state.js';
import { bindEscapeClose, trapFocus } from './focus-trap.js';

export const ACTIVE_PROFILE_LS = 'baklog-active-profile';
export const ITAD_SNAPSHOT_PREFIX = 'baklog-itad-snapshot';

let _status = null;
let _menuOpen = false;
let _manageRelease = null;

function el(id) {
  return document.getElementById(id);
}

export function activeProfileId() {
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
    localStorage.removeItem(`${PREFS_KEY}${suffix}`);
    localStorage.removeItem(`${ITAD_SNAPSHOT_PREFIX}${suffix}`);
    localStorage.removeItem(`baklog-fetcher-auth-cooldown${suffix}`);
    localStorage.removeItem(`baklog-reconnect-dismissed${suffix}`);
    localStorage.removeItem(`baklog-itad-last-auto-run${suffix}`);
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
  const res = await fetch(path, opts);
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
  menu.hidden = false;
  trigger.setAttribute('aria-expanded', 'true');
}

function renderMenuList() {
  const list = el('profileMenuList');
  if (!list || !_status) return;
  const active = _status.active;
  const rows = (_status.profiles || []).map((p) => {
    const selected = p.id === active;
    return `<button type="button" role="menuitem" class="profile-menu-option w-full text-left px-3 py-2 text-sm text-slate-200 hover:bg-slate-700/60 ${selected ? 'profile-menu-option-active' : ''}" data-profile-switch="${p.id}">${escapeHtml(p.label || p.id)}${selected ? ' ✓' : ''}</button>`;
  });
  list.innerHTML = rows.join('');
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

async function switchProfile(id) {
  closeMenu();
  const { personalStore } = await import('./personal-store.js');
  await personalStore.prepareForProfileSwitch();
  await api('POST', '/api/profiles/active', { id });
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
    if (_menuOpen) closeMenu();
    else openMenu();
  });

  menu.addEventListener('click', (e) => {
    const sw = e.target.closest('[data-profile-switch]');
    if (sw) {
      const id = sw.getAttribute('data-profile-switch');
      if (id && id !== _status?.active) switchProfile(id).catch((err) => alert(err.message));
      return;
    }
    if (e.target.closest('[data-profile-manage]')) {
      populateDeleteSelect();
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

  for (const id of ['profileRenameInput', 'profileNewName', 'profileDeleteSelect']) {
    el(id)?.addEventListener('input', clearManageMessages);
    el(id)?.addEventListener('change', clearManageMessages);
  }

  bindEscapeClose(el('profileManageModal'), closeManageModal);
}

export async function initProfiles() {
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
