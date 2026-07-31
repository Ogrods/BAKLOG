/** Boot + in-app update flow against /api/update-check and /api/update/* (frozen installs). */

import { baklogFetch } from "./api-client.js";
import { escapeHtml } from "./dom-util.js";

/** @deprecated legacy session flag; per-version dismiss uses server + localStorage mirror */
export const UPDATE_BANNER_DISMISS_KEY = "baklog.updateBannerDismissed";
export const UPDATE_DISMISSED_VERSION_KEY = "baklog.updateDismissedVersion";
/** Survives post-apply reload so api-client keeps suppressing update-endpoint noise. */
export const UPDATE_SUPPRESS_NETWORK_KEY = "baklog.suppressNetworkErrors";

const UPDATE_STATUS_POLL_MS = 800;
const POST_APPLY_POLL_MS = 1000;
const POST_APPLY_TIMEOUT_MS = 90000;
export const POST_APPLY_RECOVERY_MESSAGE =
  "If BAKLOG didn't restart, open BAKLOG Tray from the Start Menu (or run BAKLOG Tray.exe).";
const UPDATE_MODAL_ID = "updateReleaseModal";
const UPDATE_INSTALL_MODAL_ID = "updateInstallConfirmModal";
const UPDATE_TOAST_ID = "updateNoticeToast";

/** @type {AbortController | null} */
let _modalKeyAbort = null;

/** @type {{ installSource: string | null, arpVersionMismatch: boolean }} */
let _installHints = { installSource: null, arpVersionMismatch: false };

/**
 * Mark expected server downtime during Install & restart (window + sessionStorage).
 * @param {boolean} on
 */
export function setUpdateRestartSuppress(on) {
  if (typeof window === "undefined") return;
  window.__baklogSuppressNetworkErrors = !!on;
  try {
    if (on) window.sessionStorage?.setItem(UPDATE_SUPPRESS_NETWORK_KEY, "1");
    else window.sessionStorage?.removeItem(UPDATE_SUPPRESS_NETWORK_KEY);
  } catch {
    /* private mode / disabled storage */
  }
}

/** Restore suppress flag after a post-apply reload (sessionStorage survived). */
export function restoreUpdateRestartSuppressFromSession() {
  if (typeof window === "undefined") return false;
  try {
    if (window.sessionStorage?.getItem(UPDATE_SUPPRESS_NETWORK_KEY) === "1") {
      window.__baklogSuppressNetworkErrors = true;
      return true;
    }
  } catch {
    /* ignore */
  }
  return false;
}

export function clearUpdateRestartSuppress() {
  setUpdateRestartSuppress(false);
}

/**
 * @param {unknown} data
 * @returns {{ installSource: string | null, arpVersionMismatch: boolean }}
 */
export function installHintsFromPayload(data) {
  if (!data || typeof data !== "object") {
    return { installSource: null, arpVersionMismatch: false };
  }
  const installSource =
    typeof data.install_source === "string" && data.install_source.trim()
      ? data.install_source.trim()
      : null;
  return {
    installSource,
    arpVersionMismatch: data.arp_version_mismatch === true,
  };
}

/** @param {unknown} data */
export function rememberInstallHints(data) {
  _installHints = installHintsFromPayload(data);
}

/** @internal Vitest helper */
export function _resetInstallHintsForTests() {
  _installHints = { installSource: null, arpVersionMismatch: false };
}

/**
 * Footnote for Setup installs where zip apply does not refresh Add/Remove Programs.
 * @param {{ installSource?: string | null, arpVersionMismatch?: boolean }} [hints]
 */
export function renderSetupArpFootnote(hints = _installHints) {
  if (hints?.installSource !== "setup" && !hints?.arpVersionMismatch) return "";
  return (
    '<p class="text-xs text-slate-500 mt-2">' +
    "Installed with BAKLOG-Setup.exe? Add/Remove Programs may still show an older version after in-app updates. " +
    "Re-run the installer from the release page when you want Settings to match, or ignore it if the app version looks correct." +
    "</p>"
  );
}

/**
 * @param {unknown} data
 * @returns {{
 *   ok: true,
 *   current: string,
 *   latest: string | null,
 *   updateAvailable: boolean,
 *   url: string | null,
 *   downloadUrl: string | null,
 *   sha256: string | null,
 *   applySupported: boolean,
 *   applyBlockedReason: string | null,
 *   applyBlockedMessage: string | null,
 *   runtimeLabel: string | null,
 *   releaseNotes: string | null,
 *   publishedAt: string | null,
 *   dismissed: boolean,
 *   fetchersInFlight: boolean,
 *   signInActive: boolean,
 * } | { ok: false, error: string }}
 */
export function parseUpdateCheckResponse(data) {
  if (!data || typeof data !== "object") {
    return { ok: false, error: "Invalid update-check response" };
  }
  const err = typeof data.error === "string" ? data.error.trim() : "";
  if (err) return { ok: false, error: err };
  const current = typeof data.current === "string" ? data.current : "";
  const latest =
    typeof data.latest === "string" && data.latest.trim()
      ? data.latest.trim()
      : null;
  const url =
    typeof data.url === "string" && data.url.trim() ? data.url.trim() : null;
  const downloadUrl =
    typeof data.download_url === "string" && data.download_url.trim()
      ? data.download_url.trim()
      : null;
  const sha256 =
    typeof data.sha256 === "string" && data.sha256.trim()
      ? data.sha256.trim()
      : null;
  const releaseNotes =
    typeof data.release_notes === "string" && data.release_notes.trim()
      ? data.release_notes.trim()
      : null;
  const publishedAt =
    typeof data.published_at === "string" && data.published_at.trim()
      ? data.published_at.trim()
      : null;
  const blockedReason =
    typeof data.apply_blocked_reason === "string" &&
    data.apply_blocked_reason.trim()
      ? data.apply_blocked_reason.trim()
      : null;
  const blockedMessage =
    typeof data.apply_blocked_message === "string" &&
    data.apply_blocked_message.trim()
      ? data.apply_blocked_message.trim()
      : null;
  return {
    ok: true,
    current,
    latest,
    updateAvailable: data.update_available === true,
    url,
    downloadUrl,
    sha256,
    applySupported: data.apply_supported === true,
    applyBlockedReason: blockedReason,
    applyBlockedMessage: blockedMessage,
    runtimeLabel:
      typeof data.runtime_label === "string" ? data.runtime_label : null,
    releaseNotes,
    publishedAt,
    dismissed: data.dismissed === true,
    fetchersInFlight: data.fetchers_in_flight === true,
    signInActive: data.sign_in_active === true,
    ...installHintsFromPayload(data),
  };
}

/** @param {{ fetchersInFlight?: boolean, signInActive?: boolean }} parsed */
function updateMutationsBlocked(parsed) {
  return parsed.fetchersInFlight === true || parsed.signInActive === true;
}

/** @param {{ latest: string | null, dismissed?: boolean }} parsed */
export function isUpdateBannerDismissed(parsed) {
  if (parsed.dismissed === true) return true;
  if (!parsed.latest) return false;
  try {
    const stored = localStorage.getItem(UPDATE_DISMISSED_VERSION_KEY);
    return stored === parsed.latest;
  } catch {
    return false;
  }
}

/** @param {string} version */
export function rememberDismissedVersion(version) {
  if (!version) return;
  try {
    localStorage.setItem(UPDATE_DISMISSED_VERSION_KEY, version);
  } catch {
    /* quota / private mode */
  }
}

/** @param {{ current: string, latest: string | null, url: string | null }} parsed */
export function formatUpdateAvailableMessage(parsed) {
  const urlPart = parsed.url ? ` Release page: ${parsed.url}` : "";
  return `Update available: v${parsed.latest} (you have v${parsed.current}).${urlPart}`;
}

/** @param {{ current: string }} parsed */
export function formatUpToDateMessage(parsed) {
  return `You're on the latest release (v${parsed.current}).`;
}

/**
 * @param {string | null | undefined} message
 * @param {string | null | undefined} [code]
 */
export function mapUpdateError(message, code = null) {
  const text = (message || "").trim();
  if (code === "fetchers_running") {
    return "Finish or stop fetchers in Fetcher health, then try again.";
  }
  if (code === "sign_in_active") {
    return "Finish or cancel the sign-in window before updating.";
  }
  if (code === "dev_runtime") {
    return "Updates install only in the desktop app, not the dev server.";
  }
  if (text) return text;
  return "Update failed.";
}

/**
 * @param {{
 *   applyBlockedMessage?: string | null,
 *   applySupported?: boolean,
 *   fetchersInFlight?: boolean,
 *   signInActive?: boolean,
 * }} parsed
 */
export function renderApplyBlockedHint(parsed) {
  if (parsed.applySupported && !updateMutationsBlocked(parsed)) return "";
  const msg = parsed.signInActive
    ? mapUpdateError("", "sign_in_active")
    : parsed.fetchersInFlight
      ? mapUpdateError("", "fetchers_running")
      : parsed.applyBlockedMessage?.trim();
  if (!msg) return "";
  return `<p class="update-blocked-hint text-sm text-slate-400 mt-1">${escapeHtml(msg)}</p>`;
}

/**
 * @param {{
 *   latest: string | null,
 *   url: string | null,
 *   current: string,
 *   applySupported?: boolean,
 *   applyBlockedMessage?: string | null,
 *   fetchersInFlight?: boolean,
 *   signInActive?: boolean,
 *   releaseNotes?: string | null,
 * }} parsed
 */
export function renderUpdateBannerHtml(parsed) {
  const href = parsed.url || "https://github.com/Ogrods/BAKLOG/releases/latest";
  const canUpdateNow = parsed.applySupported && !updateMutationsBlocked(parsed);
  const updateBtn = canUpdateNow
    ? '<button type="button" class="update-available-banner-apply ml-2 text-sky-300 hover:underline">Update now</button>'
    : "";
  return (
    '<div class="migration-banner-body update-available-banner-body">' +
    `<span class="text-amber-400">BAKLOG v${escapeHtml(parsed.latest || "")} is available (you have v${escapeHtml(parsed.current)}).</span> ` +
    updateBtn +
    `<button type="button" class="update-available-banner-notes ml-2 text-sky-300 hover:underline">What's new</button>` +
    `<a href="${escapeHtml(href)}" class="update-available-banner-release ml-2 text-sky-300 hover:underline" target="_blank" rel="noopener noreferrer">Release page</a>` +
    '<button type="button" class="update-available-banner-snooze ml-2 text-slate-400 hover:text-slate-200 text-sm">Remind me later</button>' +
    renderApplyBlockedHint(parsed) +
    "</div>"
  );
}

/**
 * @param {{ version: string | null }} status
 */
export function renderUpdateReadyBannerHtml(status) {
  const version = status.version || "new";
  return (
    '<div class="migration-banner-body update-ready-banner-body">' +
    `<span class="text-amber-400">Update v${escapeHtml(version)} downloaded and verified.</span> ` +
    '<button type="button" class="update-ready-banner-install ml-2 text-sky-300 hover:underline">Install &amp; restart</button>' +
    '<button type="button" class="update-ready-banner-discard ml-2 text-slate-400 hover:text-slate-200 text-sm">Discard download</button>' +
    '<button type="button" class="update-ready-banner-later ml-2 text-slate-400 hover:text-slate-200 text-sm">Not yet</button>' +
    "</div>"
  );
}

/**
 * @param {ReturnType<typeof parseUpdateStatusResponse> & { ok: true }} status
 * @param {{ cancellable?: boolean }} [opts]
 */
export function renderUpdateProgressHtml(status, { cancellable = false } = {}) {
  const msg = formatProgressMessage(status);
  const cancelBtn =
    cancellable && status.phase === "downloading"
      ? '<button type="button" class="update-progress-cancel ml-2 text-slate-400 hover:text-slate-200 text-sm">Cancel download</button>'
      : "";
  return (
    `<div class="migration-banner-body update-progress-banner-body">` +
    `<span class="text-amber-400">${escapeHtml(msg)}</span> ${cancelBtn}` +
    "</div>"
  );
}

/**
 * @param {{
 *   latest: string | null,
 *   current: string,
 *   url: string | null,
 *   releaseNotes?: string | null,
 *   applySupported?: boolean,
 *   applyBlockedMessage?: string | null,
 *   fetchersInFlight?: boolean,
 *   signInActive?: boolean,
 * }} parsed
 */
export function renderUpdateModalHtml(parsed) {
  const href = parsed.url || "https://github.com/Ogrods/BAKLOG/releases/latest";
  const notes = parsed.releaseNotes
    ? `<pre class="update-modal-notes whitespace-pre-wrap text-sm text-slate-300 max-h-64 overflow-y-auto mt-3 p-3 rounded bg-slate-900/80 border border-slate-700">${escapeHtml(parsed.releaseNotes)}</pre>`
    : '<p class="text-sm text-slate-400 mt-3">See the release page for details.</p>';
  const canUpdateNow = parsed.applySupported && !updateMutationsBlocked(parsed);
  const updateBtn = canUpdateNow
    ? '<button type="button" class="update-modal-apply bg-sky-700 hover:bg-sky-600 px-3 py-2 rounded text-sm">Update now</button>'
    : "";
  return (
    `<div class="update-modal-panel bg-slate-800 border border-slate-600 rounded-lg shadow-xl max-w-lg w-full mx-4 p-6" role="dialog" aria-modal="true" aria-labelledby="updateModalTitle">` +
    `<h2 id="updateModalTitle" class="text-lg font-semibold text-slate-100">Update available: v${escapeHtml(parsed.latest || "")}</h2>` +
    `<p class="text-sm text-slate-400 mt-1">You have v${escapeHtml(parsed.current)}.</p>` +
    renderApplyBlockedHint(parsed) +
    notes +
    `<div class="flex flex-wrap gap-2 justify-end mt-4">` +
    `<a href="${escapeHtml(href)}" class="update-modal-release text-sm text-sky-300 hover:underline px-3 py-2" target="_blank" rel="noopener noreferrer">Release page</a>` +
    '<button type="button" class="update-modal-later text-sm px-3 py-2 rounded hover:bg-slate-700">Remind me later</button>' +
    updateBtn +
    "</div></div>"
  );
}

function renderInstallConfirmModalHtml(hints = _installHints) {
  return (
    `<div class="update-modal-panel bg-slate-800 border border-slate-600 rounded-lg shadow-xl max-w-md w-full mx-4 p-6" role="dialog" aria-modal="true" aria-labelledby="updateInstallTitle">` +
    '<h2 id="updateInstallTitle" class="text-lg font-semibold text-slate-100">Install and restart?</h2>' +
    '<p class="text-sm text-slate-400 mt-2">The update is downloaded and verified. BAKLOG will restart to finish installing. Your library data stays where it is.</p>' +
    renderSetupArpFootnote(hints) +
    '<div class="flex flex-wrap gap-2 justify-end mt-4">' +
    '<button type="button" class="update-install-decline text-sm px-3 py-2 rounded hover:bg-slate-700">Not yet</button>' +
    '<button type="button" class="update-install-confirm bg-sky-700 hover:bg-sky-600 px-3 py-2 rounded text-sm">Install &amp; restart</button>' +
    "</div></div>"
  );
}

export function hideUpdateBanner() {
  const banner = document.getElementById("updateAvailableBanner");
  if (!banner) return;
  banner.classList.add("hidden");
  banner.replaceChildren();
}

function setBannerHtml(html, { hidden = false } = {}) {
  const banner = document.getElementById("updateAvailableBanner");
  if (!banner) return;
  banner.replaceChildren();
  banner.insertAdjacentHTML("beforeend", html);
  banner.classList.toggle("hidden", hidden);
}

function hideUpdateModal() {
  _modalKeyAbort?.abort();
  _modalKeyAbort = null;
  const modal = document.getElementById(UPDATE_MODAL_ID);
  if (!modal) return;
  modal.classList.add("hidden");
  modal.replaceChildren();
}

function hideInstallConfirmModal() {
  _modalKeyAbort?.abort();
  _modalKeyAbort = null;
  const modal = document.getElementById(UPDATE_INSTALL_MODAL_ID);
  if (!modal) return;
  modal.classList.add("hidden");
  modal.replaceChildren();
}

/**
 * @param {HTMLElement} modal
 * @param {() => void} onClose
 */
function bindModalDismiss(modal, onClose) {
  _modalKeyAbort?.abort();
  const controller = new AbortController();
  _modalKeyAbort = controller;
  const { signal } = controller;
  modal.addEventListener(
    "click",
    (ev) => {
      if (ev.target === modal) onClose();
    },
    { signal },
  );
  modal.addEventListener(
    "keydown",
    (ev) => {
      if (ev.key === "Escape") onClose();
    },
    { signal },
  );
}

/**
 * @param {string} message
 * @param {{ error?: boolean }} [opts]
 */
export function showUpdateToast(message, { error = false } = {}) {
  if (typeof document === "undefined") return;
  let el = document.getElementById(UPDATE_TOAST_ID);
  if (!el) {
    el = document.createElement("div");
    el.id = UPDATE_TOAST_ID;
    el.className = "update-notice-toast hidden";
    el.setAttribute("role", "status");
    el.setAttribute("aria-live", "polite");
    document.body.appendChild(el);
  }
  el.className = `update-notice-toast ${error ? "update-notice-toast-error" : "update-notice-toast-info"}`;
  el.textContent = message;
  el.classList.remove("hidden");
  clearTimeout(el._hideTimer);
  el._hideTimer = setTimeout(() => el.classList.add("hidden"), 5000);
}

/**
 * @param {object} parsed
 * @param {{ fetchFn?: typeof fetch, onNotice?: (msg: string, opts?: { error?: boolean }) => void }} [handlers]
 */
export function showUpdateModal(parsed, handlers = {}) {
  let modal = document.getElementById(UPDATE_MODAL_ID);
  if (!modal) {
    modal = document.createElement("div");
    modal.id = UPDATE_MODAL_ID;
    modal.className =
      "fixed inset-0 z-50 hidden flex items-center justify-center bg-black/60";
    modal.tabIndex = -1;
    document.body.appendChild(modal);
  }
  modal.replaceChildren();
  modal.insertAdjacentHTML("beforeend", renderUpdateModalHtml(parsed));
  modal.classList.remove("hidden");
  modal.focus();

  const close = () => hideUpdateModal();
  bindModalDismiss(modal, close);
  modal.querySelector(".update-modal-later")?.addEventListener(
    "click",
    () => {
      dismissUpdateForVersion(parsed.latest, handlers).catch(() => {});
    },
    { once: true },
  );
  modal.querySelector(".update-modal-apply")?.addEventListener(
    "click",
    () => {
      close();
      runInAppUpdateFlow(handlers).catch(() => {});
    },
    { once: true },
  );
}

/**
 * @returns {Promise<boolean>}
 */
export function confirmInstallUpdate() {
  return new Promise((resolve) => {
    let modal = document.getElementById(UPDATE_INSTALL_MODAL_ID);
    if (!modal) {
      modal = document.createElement("div");
      modal.id = UPDATE_INSTALL_MODAL_ID;
      modal.className =
        "fixed inset-0 z-[60] hidden flex items-center justify-center bg-black/60";
      modal.tabIndex = -1;
      document.body.appendChild(modal);
    }
    modal.replaceChildren();
    modal.insertAdjacentHTML("beforeend", renderInstallConfirmModalHtml());
    modal.classList.remove("hidden");
    modal.focus();

    const finish = (value) => {
      hideInstallConfirmModal();
      resolve(value);
    };
    bindModalDismiss(modal, () => finish(false));
    modal
      .querySelector(".update-install-decline")
      ?.addEventListener("click", () => finish(false), { once: true });
    modal
      .querySelector(".update-install-confirm")
      ?.addEventListener("click", () => finish(true), { once: true });
  });
}

/**
 * @param {string | null | undefined} version
 * @param {{ fetchFn?: typeof fetch }} [opts]
 */
export async function dismissUpdateForVersion(version, opts = {}) {
  if (!version) return;
  rememberDismissedVersion(version);
  hideUpdateBanner();
  hideUpdateModal();
  const fetchFn = opts.fetchFn || baklogFetch;
  try {
    await fetchFn("/api/update/dismiss", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ version }),
    });
  } catch {
    /* local mirror still applies */
  }
}

/** @deprecated use dismissUpdateForVersion */
export function dismissUpdateBannerForSession() {
  hideUpdateBanner();
}

/**
 * @param {{ fetchFn?: typeof fetch, onNotice?: (msg: string, opts?: { error?: boolean }) => void }} [handlers]
 */
export async function cancelUpdateDownload(handlers = {}) {
  const fetchFn = handlers.fetchFn || baklogFetch;
  try {
    await fetchFn("/api/update/cancel", { method: "POST" });
    hideUpdateBanner();
    handlers.onNotice?.("Update download cancelled.");
  } catch (err) {
    handlers.onNotice?.(`Could not cancel download: ${err?.message || err}`, {
      error: true,
    });
  }
}

function bindUpdateBannerHandlers(parsed, handlers = {}) {
  const banner = document.getElementById("updateAvailableBanner");
  if (!banner) return;
  banner
    .querySelector(".update-available-banner-snooze")
    ?.addEventListener("click", () => {
      dismissUpdateForVersion(parsed.latest, handlers).catch(() => {});
    });
  banner
    .querySelector(".update-available-banner-apply")
    ?.addEventListener("click", () => {
      runInAppUpdateFlow(handlers).catch(() => {});
    });
  banner
    .querySelector(".update-available-banner-notes")
    ?.addEventListener("click", () => {
      showUpdateModal(parsed, handlers);
    });
}

export async function discardReadyUpdate(handlers = {}) {
  const fetchFn = handlers.fetchFn || baklogFetch;
  try {
    await fetchFn("/api/update/discard-ready", { method: "POST" });
    hideUpdateBanner();
    handlers.onNotice?.("Downloaded update discarded.");
  } catch (err) {
    handlers.onNotice?.(`Could not discard update: ${err?.message || err}`, {
      error: true,
    });
  }
}

function bindReadyBannerHandlers(status, handlers = {}) {
  const banner = document.getElementById("updateAvailableBanner");
  if (!banner) return;
  banner
    .querySelector(".update-ready-banner-install")
    ?.addEventListener("click", () => {
      runApplyReadyUpdate(handlers).catch(() => {});
    });
  banner
    .querySelector(".update-ready-banner-discard")
    ?.addEventListener("click", () => {
      discardReadyUpdate(handlers).catch(() => {});
    });
  banner
    .querySelector(".update-ready-banner-later")
    ?.addEventListener("click", () => {
      handlers.onNotice?.(
        "Update ready — choose Install & restart when you want.",
      );
    });
}

/**
 * @param {ReturnType<typeof parseUpdateStatusResponse> & { ok: true }} status
 * @param {{ fetchFn?: typeof fetch, onNotice?: (msg: string, opts?: { error?: boolean }) => void }} [handlers]
 */
export function showReadyToInstallBanner(status, handlers = {}) {
  setBannerHtml(renderUpdateReadyBannerHtml(status));
  bindReadyBannerHandlers(status, handlers);
}

/**
 * @param {{ latest: string | null, url: string | null, current: string, applySupported?: boolean, releaseNotes?: string | null, dismissed?: boolean, applyBlockedMessage?: string | null }} parsed
 * @param {{ onNotice?: (msg: string, opts?: { error?: boolean }) => void, fetchFn?: typeof fetch }} [handlers]
 */
export function showUpdateBanner(parsed, handlers = {}) {
  if (isUpdateBannerDismissed(parsed)) {
    return;
  }
  setBannerHtml(renderUpdateBannerHtml(parsed));
  bindUpdateBannerHandlers(parsed, handlers);
}

/**
 * @param {unknown} data
 */
export function parseUpdateStatusResponse(data) {
  if (!data || typeof data !== "object") {
    return { ok: false, error: "Invalid update status response" };
  }
  return {
    ok: true,
    phase: typeof data.phase === "string" ? data.phase : "idle",
    progressBytes: Number(data.progress_bytes) || 0,
    totalBytes: data.total_bytes == null ? null : Number(data.total_bytes) || 0,
    version: typeof data.version === "string" ? data.version : null,
    error: typeof data.error === "string" ? data.error : null,
    ready: data.ready === true,
    canApply: data.can_apply === true,
  };
}

function formatProgressMessage(status) {
  if (status.phase === "downloading") {
    if (status.totalBytes) {
      const pct = Math.min(
        100,
        Math.round((status.progressBytes / status.totalBytes) * 100),
      );
      return `Downloading update… ${pct}%`;
    }
    return "Downloading update…";
  }
  if (status.phase === "ready")
    return "Update downloaded and verified. Ready to install.";
  if (status.phase === "applying")
    return "Installing update and restarting BAKLOG…";
  if (status.phase === "error") return mapUpdateError(status.error);
  return "";
}

function bindProgressCancel(handlers = {}) {
  const banner = document.getElementById("updateAvailableBanner");
  banner
    ?.querySelector(".update-progress-cancel")
    ?.addEventListener("click", () => {
      cancelUpdateDownload(handlers).catch(() => {});
    });
}

function showUpdateError(message, handlers = {}) {
  setBannerHtml(
    `<div class="migration-banner-body"><span class="text-red-400">${escapeHtml(mapUpdateError(message))}</span></div>`,
  );
  handlers.onNotice?.(mapUpdateError(message), { error: true });
}

/**
 * @param {{ fetchFn?: typeof fetch, onNotice?: (msg: string, opts?: { error?: boolean }) => void, sleepMs?: number, timeoutMs?: number }} [opts]
 */
export async function pollPostApplyOutcome(opts = {}) {
  const fetchFn = opts.fetchFn || baklogFetch;
  const sleepMs = opts.sleepMs ?? POST_APPLY_POLL_MS;
  const deadline = Date.now() + (opts.timeoutMs ?? POST_APPLY_TIMEOUT_MS);
  // Server is shutting down for restart — suppress network error persistence
  // (window flag + sessionStorage so a mid-apply reload stays quiet until boot).
  setUpdateRestartSuppress(true);
  try {
    while (Date.now() < deadline) {
      try {
        const [statusRes, resultRes] = await Promise.all([
          fetchFn("/api/update/status"),
          fetchFn("/api/update/apply-result"),
        ]);
        const resultPayload = await resultRes.json().catch(() => ({}));
        if (
          resultPayload?.acknowledged === true &&
          resultPayload?.success === true
        ) {
          clearUpdateRestartSuppress();
          return { ok: true, version: resultPayload.version || null };
        }
        const applyResult = resultPayload?.result;
        if (applyResult && applyResult.ok === false) {
          const msg = mapUpdateError(
            String(applyResult.error || "Update apply failed"),
          );
          showUpdateError(msg, opts);
          throw new Error(msg);
        }
        if (applyResult && applyResult.ok === true) {
          clearUpdateRestartSuppress();
          return { ok: true, version: applyResult.version || null };
        }
        const status = parseUpdateStatusResponse(
          await statusRes.json().catch(() => ({})),
        );
        if (status.ok && status.phase === "error" && status.error) {
          const msg = mapUpdateError(status.error);
          showUpdateError(msg, opts);
          throw new Error(msg);
        }
      } catch (err) {
        if (
          err instanceof Error &&
          err.message &&
          !/fetch|network|failed to fetch|not responding/i.test(err.message)
        ) {
          throw err;
        }
      }
      await new Promise((resolve) => setTimeout(resolve, sleepMs));
    }
    setBannerHtml(
      `<div class="migration-banner-body"><span class="text-amber-400">${escapeHtml(POST_APPLY_RECOVERY_MESSAGE)}</span></div>`,
    );
    opts.onNotice?.(POST_APPLY_RECOVERY_MESSAGE);
  } finally {
    // Success paths clear suppress. Timeout keeps sessionStorage so the
    // relaunched tab stays quiet until boot calls clearUpdateRestartSuppress.
    restoreUpdateRestartSuppressFromSession();
  }
}

/**
 * @param {{ fetchFn?: typeof fetch, onNotice?: (msg: string, opts?: { error?: boolean }) => void, sleepMs?: number }} [opts]
 */
export async function pollUpdateStatusUntilDone(opts = {}) {
  const fetchFn = opts.fetchFn || baklogFetch;
  const sleepMs = opts.sleepMs ?? UPDATE_STATUS_POLL_MS;
  for (;;) {
    const res = await fetchFn("/api/update/status");
    const data = await res.json().catch(() => ({}));
    const status = parseUpdateStatusResponse(data);
    if (!status.ok)
      throw new Error(status.error || "Update status unavailable");
    if (status.phase !== "error") {
      setBannerHtml(renderUpdateProgressHtml(status, { cancellable: true }));
      bindProgressCancel(opts);
    }
    if (
      status.phase === "ready" ||
      status.phase === "error" ||
      status.phase === "idle"
    ) {
      return status;
    }
    if (status.phase === "applying") return status;
    await new Promise((resolve) => setTimeout(resolve, sleepMs));
  }
}

/**
 * @param {{ fetchFn?: typeof fetch, onNotice?: (msg: string, opts?: { error?: boolean }) => void }} [opts]
 */
export async function runApplyReadyUpdate(opts = {}) {
  const fetchFn = opts.fetchFn || baklogFetch;
  const confirmed = await confirmInstallUpdate();
  if (!confirmed) {
    const res = await fetchFn("/api/update/status");
    const status = parseUpdateStatusResponse(
      await res.json().catch(() => ({})),
    );
    if (status.ok && status.canApply) {
      showReadyToInstallBanner(status, opts);
    }
    opts.onNotice?.("Update ready — choose Install & restart when you want.");
    return { ok: true, ready: true, applied: false };
  }

  const applyRes = await fetchFn("/api/update/apply", { method: "POST" });
  const applyPayload = await applyRes.json().catch(() => ({}));
  if (!applyRes.ok || applyPayload.ok === false) {
    const msg = mapUpdateError(applyPayload.error, applyPayload.error_code);
    showUpdateError(msg, opts);
    throw new Error(msg);
  }

  setBannerHtml(
    '<div class="migration-banner-body"><span class="text-amber-400">Installing update and restarting BAKLOG…</span></div>',
  );
  opts.onNotice?.("Installing update and restarting BAKLOG…");
  await pollPostApplyOutcome(opts);
  return { ok: true, applied: true, version: applyPayload.version };
}

/**
 * @param {{ fetchFn?: typeof fetch, onNotice?: (msg: string, opts?: { error?: boolean }) => void, sleepMs?: number }} [opts]
 */
export async function runInAppUpdateFlow(opts = {}) {
  const fetchFn = opts.fetchFn || baklogFetch;

  const downloadRes = await fetchFn("/api/update/download", { method: "POST" });
  const downloadPayload = await downloadRes.json().catch(() => ({}));
  if (!downloadRes.ok || downloadPayload.ok === false) {
    const msg = mapUpdateError(
      downloadPayload.error,
      downloadPayload.error_code,
    );
    showUpdateError(msg, opts);
    throw new Error(msg);
  }

  const status = await pollUpdateStatusUntilDone(opts);
  if (status.phase === "error") {
    const msg = mapUpdateError(status.error);
    showUpdateError(msg, opts);
    throw new Error(msg);
  }
  if (!status.canApply) {
    const msg = "Update package is not ready to apply";
    showUpdateError(msg, opts);
    throw new Error(msg);
  }

  const confirmed =
    typeof opts.confirmInstall === "function"
      ? await opts.confirmInstall()
      : await confirmInstallUpdate();
  if (!confirmed) {
    showReadyToInstallBanner(status, opts);
    opts.onNotice?.("Update ready — choose Install & restart when you want.");
    return { ok: true, ready: true, applied: false };
  }

  const applyRes = await fetchFn("/api/update/apply", { method: "POST" });
  const applyPayload = await applyRes.json().catch(() => ({}));
  if (!applyRes.ok || applyPayload.ok === false) {
    const msg = mapUpdateError(applyPayload.error, applyPayload.error_code);
    showUpdateError(msg, opts);
    throw new Error(msg);
  }

  setBannerHtml(
    '<div class="migration-banner-body"><span class="text-amber-400">Installing update and restarting BAKLOG…</span></div>',
  );
  opts.onNotice?.("Installing update and restarting BAKLOG…");
  await pollPostApplyOutcome(opts);
  return {
    ok: true,
    applied: true,
    version: applyPayload.version || status.version,
  };
}

/**
 * @param {{ fetchFn?: typeof fetch, frozen?: boolean, onNotice?: (msg: string, opts?: { error?: boolean }) => void }} [opts]
 */
export async function acknowledgeApplyResultOnBoot(opts = {}) {
  if (opts.frozen === false) return { ok: true, acknowledged: false };
  const fetchFn = opts.fetchFn || baklogFetch;
  restoreUpdateRestartSuppressFromSession();
  try {
    const res = await fetchFn("/api/update/apply-result");
    if (!res.ok) return { ok: false };
    const data = await res.json().catch(() => ({}));
    if (data?.acknowledged === true && data?.success === true) {
      const version =
        typeof data.version === "string" && data.version.trim()
          ? data.version.trim()
          : "";
      const msg = version
        ? `Updated to v${version}.`
        : "Update installed successfully.";
      hideUpdateBanner();
      showUpdateToast(msg);
      opts.onNotice?.(msg);
      clearUpdateRestartSuppress();
      return { ok: true, acknowledged: true, success: true, version };
    }
    return {
      ok: true,
      acknowledged: false,
      result: data?.result ?? null,
    };
  } catch {
    return { ok: false };
  }
}

/**
 * @param {{ fetchFn?: typeof fetch, frozen?: boolean, onNotice?: (msg: string, opts?: { error?: boolean }) => void }} [opts]
 */
export async function syncReadyUpdateFromStatus(opts = {}) {
  if (opts.frozen === false) return { ok: true, ready: false };
  const fetchFn = opts.fetchFn || baklogFetch;
  try {
    const res = await fetchFn("/api/update/status");
    if (!res.ok) return { ok: false };
    const status = parseUpdateStatusResponse(
      await res.json().catch(() => ({})),
    );
    if (status.ok && status.phase === "ready" && status.canApply) {
      showReadyToInstallBanner(status, opts);
      return { ok: true, ready: true, status };
    }
    return { ok: true, ready: false, status };
  } catch {
    return { ok: false };
  }
}

/**
 * @param {{ source?: 'boot' | 'manual', frozen?: boolean, fetchFn?: typeof fetch, onNotice?: (msg: string, opts?: { error?: boolean }) => void, checkOnBoot?: boolean }} [opts]
 */
export async function checkForUpdates(opts = {}) {
  const fetchFn = opts.fetchFn || fetch;
  const source = opts.source || "manual";
  const frozen = opts.frozen === true;
  if (source === "boot") {
    if (!frozen) return { skipped: true, reason: "not-frozen" };
    if (opts.checkOnBoot === false)
      return { skipped: true, reason: "pref-disabled" };
  }

  const handlers = {
    fetchFn: opts.fetchFn || baklogFetch,
    onNotice: opts.onNotice,
  };

  if (source === "manual" && opts.frozen !== false) {
    const readySync = await syncReadyUpdateFromStatus({
      ...handlers,
      frozen: true,
    });
    if (readySync.ready) {
      opts.onNotice?.(
        `Update v${readySync.status?.version || ""} is ready to install.`,
      );
      return {
        ok: true,
        updateAvailable: true,
        ready: true,
        status: readySync.status,
      };
    }
  }

  try {
    const res = await fetchFn("/api/update-check");
    if (!res.ok) {
      const msg = `Could not check for updates (server returned ${res.status}).`;
      if (source === "manual") opts.onNotice?.(msg, { error: true });
      return { ok: false, error: msg };
    }
    const data = await res.json().catch(() => ({}));
    rememberInstallHints(data);
    const parsed = parseUpdateCheckResponse(data);
    if (!parsed.ok) {
      const msg = `Could not check for updates: ${parsed.error}`;
      if (source === "manual") opts.onNotice?.(msg, { error: true });
      return { ok: false, error: parsed.error };
    }
    if (parsed.updateAvailable) {
      if (source === "boot") {
        showUpdateBanner(parsed, handlers);
      } else {
        showUpdateModal(parsed, handlers);
      }
      return { ok: true, updateAvailable: true, parsed };
    }
    if (source === "manual") opts.onNotice?.(formatUpToDateMessage(parsed));
    return { ok: true, updateAvailable: false, parsed };
  } catch (err) {
    const msg = `Update check failed: ${err?.message || err}`;
    if (source === "manual") opts.onNotice?.(msg, { error: true });
    return { ok: false, error: msg };
  }
}

/** @internal Vitest helper */
export function _resetUpdateBannerForTests() {
  try {
    sessionStorage.removeItem(UPDATE_BANNER_DISMISS_KEY);
    localStorage.removeItem(UPDATE_DISMISSED_VERSION_KEY);
  } catch {
    /* ignore */
  }
  hideUpdateBanner();
  hideUpdateModal();
  hideInstallConfirmModal();
  document.getElementById(UPDATE_TOAST_ID)?.remove();
}
