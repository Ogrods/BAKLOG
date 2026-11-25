import {
  baklogFetch,
  beginConnectNetworkSuppress,
  endConnectNetworkSuppress,
  urlWithStreamTicket,
} from "./api-client.js";
import {
  getAccessToken,
  isAccountAuthMode,
  proFeaturesUnlocked,
  refreshAccountPlan,
} from "./auth-gate.js";
import {
  capabilityStatus,
  getProSettings,
  setProSettings,
} from "./pro-capabilities.js";
import { isPageHidden, registerPausable } from "./visibility.js";
import { escapeAttr, escapeHtml, isSafeHttpUrl } from "./dom-util.js";
import { bindEscapeClose, trapFocus } from "./focus-trap.js";
import { FETCHER_AUTH_PROVIDER } from "./fetcher-registry.js";
import { startMetrics, stopMetrics } from "./anon-metrics.js";
import { savePrefs } from "./prefs.js";
import { state } from "./state.js";
import { buildCardHtml } from "./connections-card-html.js";
import {
  wireMasterPasswordSave,
  wireSecretsBundle,
} from "./connections-secrets-ui.js";
import {
  authStatusLoaded,
  connectedProviderCount,
  getAuthStatusSnapshot,
  ingestAuthStatusProviders,
  isItchTabAvailable,
  isProviderConnected,
  providerForFetcher,
  providerStatus,
} from "./connections-status.js";
import {
  PROVIDER_GROUPS,
  displayStatus,
  groupConnectNote,
  groupRepFor,
  railEntries,
  renderConnRailHtml,
  syncConnRailSelection,
} from "./connections-rail.js";
import {
  bindCloudMirrorUi,
  handleCloudMirrorClear,
  handleCloudMirrorImport,
  handleCloudMirrorSyncNow,
  handleCloudMirrorToggle,
  refreshCloudMirrorUploadStatus,
  renderCloudMirrorPrefsDom,
} from "./connections-cloud-mirror.js";

export { openCloudMirrorImportDialog } from "./connections-cloud-mirror.js";
export { localProviderFooterCopy } from "./connections-card-html.js";

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
export { isItadDealsAvailable } from "./itad-deal-gate.js";
export {
  displayStatus,
  groupRepFor,
  combinedGroupStatus,
  groupRailPill,
} from "./connections-rail.js";

let _chromiumAvailable = true;
let _serverFrozen = false;

let _connPopoverRelease = null;

let reconnectProviders = new Set();
/** Most recently flagged provider for banner / deep-link focus. */
let _lastReconnectFocusProvider = null;

let pollTimer = null;
// True while refreshConnections() is running, so the baklog:auth-status listener
// (below) doesn't redundantly re-render — refreshConnections renders itself.
let _connRefreshInFlight = false;
/** Shared promise so overlapping refreshConnections callers await one run. */
let _connRefreshPromise = null;
let _connRenderFingerprint = "";
let _connAuthFingerprint = "";

const POST_CONNECT_FAST_POLL_MS = 3000;
const POST_CONNECT_FAST_POLL_MAX_MS = 30_000;
let postConnectFastPollTimer = null;
let postConnectFastPollStopAt = 0;
/** Active Connect EventSource by provider (cancel / error teardown). */
const _activeConnectStreams = new Map();
/** Latest Connect flow id per provider; a superseded flow must not tear down shared UI. */
const _connectFlowIds = new Map();
let _connectFlowSeq = 0;

/** Close any prior Connect stream for this provider, then register `es`. */
export function replaceActiveConnectStream(provider, es) {
  const prev = _activeConnectStreams.get(provider);
  if (prev && prev !== es) {
    try {
      prev.onerror = null;
      prev.close();
    } catch {
      /* noop */
    }
    _activeConnectStreams.delete(provider);
  }
  if (es) _activeConnectStreams.set(provider, es);
  return prev || null;
}

let gridWired = false;
let noteSaveTimer = null;

let chromeWired = false;

let _selectedKey = "steam";

let _secretsCorrupt = false;

function ensureSelectedKey() {
  if (getAuthStatusSnapshot().some((p) => p.key === _selectedKey)) return;
  const rep = groupRepFor(_selectedKey);
  if (
    PROVIDER_GROUPS[rep] &&
    PROVIDER_GROUPS[rep].members.some((k) =>
      getAuthStatusSnapshot().some((p) => p.key === k),
    )
  ) {
    _selectedKey = rep;
    return;
  }
  const steam = getAuthStatusSnapshot().find((p) => p.key === "steam");
  _selectedKey = steam?.key || getAuthStatusSnapshot()[0]?.key || "steam";
}

function renderHero() {
  const countEl = document.getElementById("connHeroCount");

  const fillEl = document.getElementById("connProgressFill");

  if (!countEl || !fillEl) return;

  if (!getAuthStatusSnapshot().length) {
    countEl.textContent = "Loading connections…";

    fillEl.style.width = "0%";

    return;
  }

  const entries = railEntries();

  const connected = entries.filter((e) => e.status === "connected").length;

  const total = entries.length;

  countEl.textContent = `${connected} of ${total} stores connected`;

  fillEl.style.width = total ? `${(connected / total) * 100}%` : "0%";
}

function renderOnboard() {
  const el = document.getElementById("connOnboard");

  if (!el) return;

  if (!getAuthStatusSnapshot().length || connectedProviderCount() > 0) {
    el.innerHTML = "";

    el.hidden = true;

    return;
  }

  el.hidden = false;

  el.innerHTML = `

    <div class="conn-onboard" role="region" aria-label="Get started">

      <p class="conn-onboard-title">You have 0 stores connected</p>

      <p class="conn-onboard-lead">Start with Steam if that is where your games live - one sign-in imports the whole library. Nothing on Steam? Epic, GOG, and Prime Gaming connect the same way, and their free games fill a backlog fast.</p>

      <button type="button" class="conn-onboard-btn" data-conn-start-steam title="Connect Steam - imports your library via browser sign-in">Start with Steam</button>

      <p class="conn-onboard-muted">or pick any store from the list below</p>

    </div>`;
}


function captureConnNoteFocus() {
  const active = document.activeElement;
  if (!active?.classList?.contains("conn-note-input")) return null;
  return {
    provider: active.dataset.noteProvider,
    selStart: active.selectionStart,
    selEnd: active.selectionEnd,
  };
}

function restoreConnNoteFocus(focusState, root) {
  if (!focusState?.provider || !root) return;
  const ta = root.querySelector(
    `.conn-note-input[data-note-provider="${focusState.provider}"]`,
  );
  if (!ta) return;
  ta.focus();
  try {
    ta.setSelectionRange(focusState.selStart, focusState.selEnd);
  } catch {
    // setSelectionRange can fail on some browsers during rapid re-render
  }
}

function renderConnPrefs() {
  const onConnect = document.getElementById("autoFetchOnConnectToggle");
  const stale24h = document.getElementById("autoFetchStale24hToggle");
  const shareStats = document.getElementById("shareAnonStatsToggle");
  if (onConnect) onConnect.checked = state.prefs.autoFetchOnConnect !== false;
  if (stale24h) stale24h.checked = state.prefs.autoFetchStale24h === true;
  if (shareStats) shareStats.checked = state.prefs.shareAnonStats === true;

  renderCloudMirrorPrefsDom();

  const alertStrip = document.getElementById("connDealAlertPrefs");
  const alertToggle = document.getElementById("dealAlertsEnabledToggle");
  const showDealAlerts =
    proFeaturesUnlocked() &&
    isAccountAuthMode() &&
    !!getAccessToken() &&
    capabilityStatus("deal_watchlist_alerts") === "live";
  if (alertStrip) alertStrip.hidden = !showDealAlerts;
  if (alertToggle && showDealAlerts) {
    alertToggle.checked = getProSettings().dealAlertsEnabled === true;
  }

  const note = document.getElementById("bgRefreshPlanNote");
  if (note) {
    if (proFeaturesUnlocked()) {
      note.textContent =
        "Pro: background refresh keeps stale stores fresh even when BAKLOG is closed to the tray.";
      note.classList.add("conn-prefs-note--pro");
    } else {
      note.textContent =
        "Auto-refresh runs while BAKLOG is open (even minimized). Pro supporters get background refresh while closed to the tray.";
      note.classList.remove("conn-prefs-note--pro");
    }
    note.hidden = false;
  }
  void refreshCloudMirrorUploadStatus();
}

async function saveProSetting(key, enabled) {
  const res = await baklogFetch("/api/pro/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ [key]: !!enabled }),
  });
  let data;
  try {
    data = await res.json();
  } catch {
    data = {};
  }
  if (!res.ok) {
    throw new Error(data.error || `Save failed (${res.status})`);
  }
  if (data.proSettings) setProSettings(data.proSettings);
  await refreshAccountPlan();
  return data;
}

async function handleDealAlertsToggle(ev) {
  const toggle = ev.target;
  const prev = !toggle.checked;
  try {
    toggle.disabled = true;
    await saveProSetting("dealAlertsEnabled", toggle.checked);
    renderConnPrefs();
  } catch (err) {
    toggle.checked = prev;
    window.alert(err?.message || "Could not save the deal alerts setting.");
  } finally {
    toggle.disabled = false;
  }
}


function connAuthFingerprint() {
  return JSON.stringify(
    getAuthStatusSnapshot().map((p) => ({
      key: p.key,
      status: p.status || "disconnected",
      connected: !!p.connected,
      available: p.available !== false,
      label: p.label || "",
    })),
  );
}

function connRenderFingerprint() {
  return JSON.stringify({
    auth: connAuthFingerprint(),
    sel: groupRepFor(_selectedKey),
    chromium: !!_chromiumAvailable,
  });
}

function renderConnectionsPaneOnly(selKey) {
  const pane = document.getElementById("connPane");
  if (!pane) return;
  const noteFocus = captureConnNoteFocus();
  if (PROVIDER_GROUPS[selKey]) {
    const members = PROVIDER_GROUPS[selKey].members
      .map((k) => getAuthStatusSnapshot().find((x) => x.key === k))
      .filter(Boolean);
    const note = groupConnectNote(selKey, members);
    pane.innerHTML = `${note}<div class="conn-card-stack">${members.map(buildCardHtml).join("")}</div>`;
  } else {
    const selected = getAuthStatusSnapshot().find((p) => p.key === selKey);
    pane.innerHTML = selected
      ? buildCardHtml(selected)
      : '<p class="text-sm text-slate-400">Select a provider on the left to get started.</p>';
  }
  restoreConnNoteFocus(noteFocus, pane);
}

function renderConnections() {
  const rail = document.getElementById("connRail");

  const pane = document.getElementById("connPane");

  if (!rail || !pane) return;

  const authFp = connAuthFingerprint();
  const fp = connRenderFingerprint();
  let selKey = groupRepFor(_selectedKey);
  if (
    fp === _connRenderFingerprint &&
    rail.innerHTML.trim() &&
    pane.innerHTML.trim()
  ) {
    return;
  }
  if (authFp === _connAuthFingerprint && rail.innerHTML.trim()) {
    syncConnRailSelection(selKey);
    renderConnectionsPaneOnly(selKey);
    _connRenderFingerprint = fp;
    return;
  }
  _connAuthFingerprint = authFp;
  _connRenderFingerprint = fp;

  renderHero();

  renderConnPrefs();

  renderOnboard();

  if (!getAuthStatusSnapshot().length) {
    rail.innerHTML = "";

    pane.innerHTML =
      '<p class="text-sm text-slate-400">Loading connections…</p>';

    return;
  }

  ensureSelectedKey();

  selKey = groupRepFor(_selectedKey);
  const entries = railEntries();
  rail.innerHTML = renderConnRailHtml(entries, selKey);

  const noteFocus = captureConnNoteFocus();

  if (PROVIDER_GROUPS[selKey]) {
    const members = PROVIDER_GROUPS[selKey].members
      .map((k) => getAuthStatusSnapshot().find((x) => x.key === k))
      .filter(Boolean);
    const note = groupConnectNote(selKey, members);
    pane.innerHTML = `${note}<div class="conn-card-stack">${members.map(buildCardHtml).join("")}</div>`;
  } else {
    const selected = getAuthStatusSnapshot().find((p) => p.key === selKey);
    pane.innerHTML = selected
      ? buildCardHtml(selected)
      : '<p class="text-sm text-slate-400">Select a provider on the left to get started.</p>';
  }

  restoreConnNoteFocus(noteFocus, pane);
}

async function pasteFromClipboard(card) {
  const log = card?.querySelector(".conn-log");
  const input = card?.querySelector(".conn-paste-panel [data-field]");
  if (!input) return;
  try {
    const text = await navigator.clipboard.readText();
    input.value = (text || "").trim();
    if (log) {
      log.classList.remove("hidden");
      log.textContent = "Pasted from clipboard.";
    }
  } catch {
    if (log) {
      log.classList.remove("hidden");
      log.textContent =
        "Could not read clipboard - paste into the field manually (Ctrl+V).";
    }
  }
}

function handleLayoutClick(ev) {
  const target = ev.target;

  if (target.id === "cloudMirrorSyncBtn") {
    void handleCloudMirrorSyncNow();
    return;
  }

  if (target.id === "cloudMirrorImportBtn") {
    void handleCloudMirrorImport();
    return;
  }

  if (target.id === "cloudMirrorClearBtn") {
    void handleCloudMirrorClear();
    return;
  }

  const startSteam = target.closest("[data-conn-start-steam]");

  if (startSteam) {
    ev.preventDefault();

    reconnectProvider("steam");

    return;
  }

  const card = target.closest(".conn-card");

  const railItem = target.closest(".conn-rail-item");

  const provider = card?.dataset.provider || railItem?.dataset.provider;

  const disconnectBtn = target.closest("[data-disconnect-quick]");

  if (disconnectBtn && provider) {
    runConnAction(provider, () => disconnectProvider(provider));

    return;
  }

  const pasteBtn = target.closest("[data-paste-clipboard]");

  if (pasteBtn && card) {
    pasteFromClipboard(card);

    return;
  }

  const epicOauthBtn = target.closest("[data-epic-oauth]");

  if (epicOauthBtn) {
    startEpicBrowserOAuth();

    return;
  }

  const openUrlBtn = target.closest("[data-open-url]");

  if (openUrlBtn && provider) {
    openManualUrl(provider);

    return;
  }

  const enableLocalBtn = target.closest("[data-enable-local]");

  if (enableLocalBtn?.dataset.provider) {
    runConnAction(enableLocalBtn.dataset.provider, () =>
      enableLocalProvider(enableLocalBtn.dataset.provider),
    );

    return;
  }

  const primaryBtn = target.closest(".conn-primary");

  if (primaryBtn?.dataset.provider) {
    runConnAction(primaryBtn.dataset.provider, () =>
      startBrowserConnect(primaryBtn.dataset.provider),
    );

    return;
  }

  const cancelBtn = target.closest("[data-cancel-connect]");

  if (cancelBtn?.dataset.provider) {
    const provider = cancelBtn.dataset.provider;
    const card = document.querySelector(
      `.conn-card[data-provider="${provider}"]`,
    );
    const log = card?.querySelector(".conn-log");
    cancelBtn.disabled = true;
    if (log) {
      log.classList.remove("hidden");
      log.textContent = "Cancelling sign-in…";
    }
    void (async () => {
      const activeEs = _activeConnectStreams.get(provider);
      if (activeEs) {
        try {
          activeEs.onerror = null;
          activeEs.close();
        } catch (_) {
          /* noop */
        }
        _activeConnectStreams.delete(provider);
      }
      stopPostConnectFastPoll();
      const ok = await cancelBrowserConnect(provider);
      if (log) {
        log.textContent = ok
          ? "Sign-in cancelled."
          : "No active sign-in to cancel.";
      }
      hideConnectCancelControl(card);
      try {
        await refreshConnections();
      } catch (_) {
        /* noop */
      }
    })();
    return;
  }

  const saveBtn = target.closest(".conn-save");

  if (saveBtn?.dataset.provider) {
    saveFormCredentials(saveBtn.dataset.provider);

    return;
  }

  if (railItem?.dataset.provider && !card) {
    _selectedKey = railItem.dataset.provider;

    renderConnections();
    queueMicrotask(() => {
      document
        .querySelector(".conn-rail-item.is-selected")
        ?.scrollIntoView({ inline: "nearest", block: "nearest" });
    });
  }
}

function handleLayoutKeydown(ev) {
  const railItem = ev.target.closest(".conn-rail-item");

  if (!railItem || !getAuthStatusSnapshot().length) return;

  const order = railEntries().map((e) => e.key);

  let idx = order.indexOf(groupRepFor(_selectedKey));

  if (idx < 0) idx = 0;

  if (ev.key === "ArrowDown") {
    ev.preventDefault();

    idx = Math.min(idx + 1, order.length - 1);
  } else if (ev.key === "ArrowUp") {
    ev.preventDefault();

    idx = Math.max(idx - 1, 0);
  } else if (ev.key === "Home") {
    ev.preventDefault();

    idx = 0;
  } else if (ev.key === "End") {
    ev.preventDefault();

    idx = order.length - 1;
  } else if (ev.key === "Enter" || ev.key === " ") {
    if (ev.target.closest("button, input, select, a")) return;

    ev.preventDefault();

    _selectedKey = railItem.dataset.provider || _selectedKey;

    renderConnections();

    return;
  } else {
    return;
  }

  _selectedKey = order[idx];

  renderConnections();

  document
    .querySelector(`.conn-rail-item[data-provider="${_selectedKey}"]`)
    ?.focus();
  document
    .querySelector(".conn-rail-item.is-selected")
    ?.scrollIntoView({ inline: "nearest", block: "nearest" });
}

function wireGridEvents() {
  if (gridWired) return;

  const container = document.getElementById("connectionsContainer");

  const layout = document.getElementById("connLayout");

  if (!container || !layout) return;

  container.addEventListener("click", handleLayoutClick);

  container.addEventListener("input", (ev) => {
    const ta = ev.target.closest(".conn-note-input");
    if (!ta) return;
    const provider = ta.dataset.noteProvider;
    if (!provider) return;
    if (!state.prefs.connectionNotes) state.prefs.connectionNotes = {};
    state.prefs.connectionNotes[provider] = ta.value;
    clearTimeout(noteSaveTimer);
    noteSaveTimer = setTimeout(() => savePrefs(), 500);
  });

  container.addEventListener("change", (ev) => {
    if (ev.target.id === "autoFetchOnConnectToggle") {
      state.prefs.autoFetchOnConnect = ev.target.checked;
      savePrefs();
    } else if (ev.target.id === "autoFetchStale24hToggle") {
      state.prefs.autoFetchStale24h = ev.target.checked;
      savePrefs();
    } else if (ev.target.id === "shareAnonStatsToggle") {
      state.prefs.shareAnonStats = ev.target.checked;
      savePrefs();
      if (ev.target.checked) startMetrics();
      else stopMetrics();
    } else if (ev.target.id === "cloudMirrorEnabledToggle") {
      void handleCloudMirrorToggle(ev);
    } else if (ev.target.id === "dealAlertsEnabledToggle") {
      void handleDealAlertsToggle(ev);
    }
  });

  layout.addEventListener("keydown", handleLayoutKeydown);

  gridWired = true;
}

function closeConnPopover() {
  _connPopoverRelease?.();
  _connPopoverRelease = null;

  const pop = document.getElementById("connPopover");

  const bd = document.getElementById("connPopoverBackdrop");

  const body = document.getElementById("connPopoverBody");

  if (pop) pop.hidden = true;

  if (bd) bd.hidden = true;

  if (body) body.innerHTML = "";
}

function openConnPopover(which) {
  const pop = document.getElementById("connPopover");

  const bd = document.getElementById("connPopoverBackdrop");

  const body = document.getElementById("connPopoverBody");

  if (!pop || !bd || !body) return;

  const tplMap = {
    howto: "tplConnHowToPopover",
    passphrase: "tplConnPassphrasePopover",
    bundle: "tplConnBundlePopover",
  };

  const tplId = tplMap[which] || "tplConnHowToPopover";

  const tpl = document.getElementById(tplId);

  if (!tpl) return;

  body.innerHTML = "";

  body.appendChild(tpl.content.cloneNode(true));

  bd.hidden = false;

  pop.hidden = false;

  if (which === "passphrase") wireMasterPasswordSave();
  if (which === "bundle") wireSecretsBundle();

  const titleMap = {
    howto: "How connections work",
    passphrase: "Encryption passphrase",
    bundle: "Portable bundle",
  };
  const dialogTitle = document.getElementById("connPopoverDialogTitle");
  if (dialogTitle) dialogTitle.textContent = titleMap[which] || "Connections";

  _connPopoverRelease?.();
  const releaseTrap = trapFocus(pop);
  const releaseEsc = bindEscapeClose(pop, closeConnPopover);
  _connPopoverRelease = () => {
    releaseTrap();
    releaseEsc();
    _connPopoverRelease = null;
  };
  pop.querySelector(".conn-popover-close")?.focus();
}

function toggleKebabMenu(force) {
  const btn = document.getElementById("connKebabBtn");

  const menu = document.getElementById("connKebabMenu");

  if (!btn || !menu) return;

  const open = typeof force === "boolean" ? force : menu.hidden;

  menu.hidden = !open;

  btn.setAttribute("aria-expanded", open ? "true" : "false");
}


function wireChromeEvents() {
  if (chromeWired) return;

  const section = document.getElementById("connectionsContainer");

  if (!section) return;

  chromeWired = true;

  section.addEventListener("click", (ev) => {
    const target = ev.target;

    if (target.closest("#connKebabBtn")) {
      toggleKebabMenu();

      return;
    }

    const openTrigger = target.closest("[data-conn-open]");

    if (openTrigger) {
      toggleKebabMenu(false);

      openConnPopover(openTrigger.dataset.connOpen);

      return;
    }

    if (
      target.closest("[data-conn-close]") ||
      target.closest("#connPopoverBackdrop")
    ) {
      closeConnPopover();

      return;
    }
  });

  // Close the kebab menu on any click outside it (the section-scoped handler
  // above only fires for clicks inside #connectionsContainer, so clicks on the
  // header or elsewhere on the page would otherwise leave the menu open).
  document.addEventListener("click", (ev) => {
    const menu = document.getElementById("connKebabMenu");

    if (!menu || menu.hidden) return;

    const target = ev.target;

    if (target.closest("#connKebabMenu") || target.closest("#connKebabBtn"))
      return;

    toggleKebabMenu(false);
  });

  document.addEventListener("keydown", (ev) => {
    if (ev.key !== "Escape") return;

    closeConnPopover();

    toggleKebabMenu(false);
  });
}

export function showReconnectBanner(providers) {
  for (const p of providers || []) {
    reconnectProviders.add(p);
    _lastReconnectFocusProvider = p;
  }

  renderReconnectBanner();
}

export function clearReconnectBanner(provider) {
  if (!provider) return;
  if (reconnectProviders.delete(provider)) {
    if (_lastReconnectFocusProvider === provider) {
      _lastReconnectFocusProvider = [...reconnectProviders].at(-1) || null;
    }
    renderReconnectBanner();
  }
}

/** Select a Connections rail card and scroll it into view (deep-link from chips/banner). */
export async function focusConnectionsProvider(provider) {
  if (!provider) return;
  _selectedKey = groupRepFor(provider);
  try {
    await refreshConnections();
  } catch {
    try {
      renderConnections();
    } catch {
      /* ignore */
    }
  }
  requestAnimationFrame(() => {
    const rail = document.getElementById("connRail");
    const item =
      rail?.querySelector(`.conn-rail-item[data-provider="${CSS.escape(_selectedKey)}"]`) ||
      rail?.querySelector(`.conn-rail-item.is-selected`);
    item?.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "smooth" });
  });
}

function renderReconnectBanner() {
  if (!reconnectProviders.size) {
    void import("./notice-toast.js").then(({ hideNoticeToast }) => {
      hideNoticeToast("authReconnectBanner");
    });
    return;
  }

  const names = [...reconnectProviders]
    .map((k) => getAuthStatusSnapshot().find((p) => p.key === k)?.label || k)
    .join(", ");

  const html = `
    <div class="migration-banner-body">
      <span>Session expired for <strong>${escapeHtml(names)}</strong>.</span>
      <span class="migration-banner-actions">
        <button type="button" class="underline" data-jump-connections title="Open Connections to refresh expired sessions">Reconnect in Connections</button>
        <button type="button" class="opacity-70" data-dismiss-auth-banner aria-label="Dismiss" title="Dismiss session expired banner">&times;</button>
      </span>
    </div>`;

  void import("./notice-toast.js").then(({ showNoticeToast, hideNoticeToast }) => {
    const el = showNoticeToast({
      id: "authReconnectBanner",
      html,
      variant: "auth",
      role: "alert",
      live: "assertive",
    });
    if (!el) return;
    el.querySelector("[data-jump-connections]")?.addEventListener("click", () => {
      const target =
        _lastReconnectFocusProvider || [...reconnectProviders].at(-1) || null;
      document.querySelector('.view-tab[data-view="connections"]')?.click();
      if (target) void focusConnectionsProvider(target);
      else renderConnections();
    });
    el.querySelector("[data-dismiss-auth-banner]")?.addEventListener(
      "click",
      () => {
        const providers = [...reconnectProviders];
        reconnectProviders.clear();
        _lastReconnectFocusProvider = null;
        hideNoticeToast("authReconnectBanner");
        try {
          document.dispatchEvent(
            new CustomEvent("baklog:reconnect-dismiss", {
              detail: { providers },
            }),
          );
        } catch (_) {
          /* no DOM (tests) */
        }
      },
    );
  });
}

function connectionStatusErrorMessage(err) {
  const status = err?.status;
  if (status === 401) {
    return isAccountAuthMode()
      ? "Session expired or not signed in. Sign in again to refresh connection status."
      : "Not authorized to load connection status.";
  }
  if (status === 503)
    return "Server secrets store is unavailable. Check server logs.";
  if (status >= 500) {
    return err?.detail
      ? `Server error loading connection status: ${err.detail}`
      : "Server error loading connection status. Check server.py logs.";
  }
  if (err?.code === "network") {
    return "Could not reach the local server (is server.py running?).";
  }
  return "Could not load connection status.";
}

function ensureConnRefreshBanner() {
  const layout = document.getElementById("connLayout");
  if (!layout) return null;
  let el = document.getElementById("connRefreshBanner");
  if (!el) {
    el = document.createElement("p");
    el.id = "connRefreshBanner";
    el.className = "conn-refresh-error text-sm text-amber-400 hidden";
    el.setAttribute("role", "status");
    layout.parentNode?.insertBefore(el, layout);
  }
  return el;
}

function showConnRefreshError(msg) {
  const el = ensureConnRefreshBanner();
  if (!el) return;
  el.textContent = msg;
  el.classList.remove("hidden");
}

function clearConnRefreshError() {
  const el = document.getElementById("connRefreshBanner");
  if (el) el.classList.add("hidden");
}

async function fetchAuthStatus() {
  let res;
  try {
    res = await baklogFetch("/api/auth/status");
  } catch (_) {
    const err = new Error("network");
    err.code = "network";
    throw err;
  }
  if (!res.ok) {
    const err = new Error(`auth status ${res.status}`);
    err.status = res.status;
    try {
      const body = await res.json();
      if (body?.error) err.detail = body.error;
    } catch {
      /* ignore */
    }
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
  if (!_secretsCorrupt) {
    void import("./notice-toast.js").then(({ hideNoticeToast }) => {
      hideNoticeToast("authSecretsBanner");
    });
    return;
  }
  const html = `
    <div class="migration-banner-body">
      <span><strong>Secrets store corrupt.</strong> Restore from a backup on Connections, or reset the store and reconnect stores.</span>
      <span class="migration-banner-actions">
        <button type="button" class="underline" data-jump-connections-secrets>Open Connections</button>
        <button type="button" class="underline" data-reset-secrets-store>Reset store</button>
      </span>
    </div>
  `;
  void import("./notice-toast.js").then(({ showNoticeToast }) => {
    const el = showNoticeToast({
      id: "authSecretsBanner",
      html,
      variant: "auth",
      role: "alert",
      live: "assertive",
    });
    if (!el) return;
    el.querySelector("[data-jump-connections-secrets]")?.addEventListener(
      "click",
      () => {
        document.querySelector('.view-tab[data-view="connections"]')?.click();
      },
    );
    el.querySelector("[data-reset-secrets-store]")?.addEventListener(
      "click",
      () => {
        void resetSecretsStoreFromBanner();
      },
    );
  });
}

async function resetSecretsStoreFromBanner() {
  const ok = window.confirm(
    "Reset the encrypted credentials store? Saved API keys and sign-in cookies for this profile will be removed. You can reconnect stores afterward.",
  );
  if (!ok) return;
  try {
    const res = await baklogFetch("/api/auth/secrets/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm: true }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      window.alert(data.error || `Reset failed (${res.status})`);
      return;
    }
    await fetchAuthStatus();
  } catch {
    window.alert("Could not reach the local server.");
  }
}

async function openManualUrl(provider) {
  const card = document.querySelector(
    `.conn-card[data-provider="${provider}"]`,
  );

  const log = card?.querySelector(".conn-log");

  if (log) {
    log.classList.remove("hidden");

    log.textContent = "Opening in your default browser…";
  }

  const res = await baklogFetch(`/api/auth/${provider}/open-url`, {
    method: "POST",
  });

  const data = await res.json().catch(() => ({}));

  if (!res.ok) {
    if (log)
      log.textContent = data.error || `Could not open browser (${res.status})`;

    return;
  }

  if (log)
    log.textContent =
      "Copy your API key from the browser tab, paste above, then Save key.";
}

async function startEpicBrowserOAuth() {
  const card = document.querySelector('.conn-card[data-provider="epic"]');

  const log = card?.querySelector(".conn-log");

  if (log) {
    log.classList.remove("hidden");

    log.textContent = "Opening Epic sign-in…";
  }

  let res;

  try {
    res = await baklogFetch("/api/auth/epic/oauth-url", { method: "POST" });
  } catch (_) {
    if (log)
      log.textContent =
        "Could not reach the local server (is server.py running?).";

    return;
  }

  const data = await res.json().catch(() => ({}));

  if (!res.ok || !data.url) {
    if (log)
      log.textContent =
        data.error || `Could not start Epic sign-in (${res.status})`;

    return;
  }

  if (!isSafeHttpUrl(data.url)) {
    if (log)
      log.textContent = "Epic returned an unexpected sign-in URL; aborting.";

    return;
  }

  window.open(data.url, "_blank", "noopener");

  startPostConnectFastPoll();

  if (log)
    log.textContent =
      "Finish signing in in the new tab - this page updates once Epic connects.";
}

async function saveFormCredentials(provider) {
  const card = document.querySelector(
    `.conn-card[data-provider="${provider}"]`,
  );

  const log = card?.querySelector(".conn-log");

  const fields = {};

  card?.querySelectorAll("[data-field]").forEach((inp) => {
    fields[inp.dataset.field] = inp.value;
  });

  if (log) {
    log.classList.remove("hidden");

    log.textContent = "Saving…";
  }

  const res = await baklogFetch(`/api/auth/${provider}/credentials`, {
    method: "PUT",

    headers: { "Content-Type": "application/json" },

    body: JSON.stringify({ fields }),
  });

  const data = await res.json().catch(() => ({}));

  if (!res.ok) {
    if (log) log.textContent = data.error || `Save failed (${res.status})`;

    return;
  }

  if (log) log.textContent = "Saved.";

  await refreshConnections();
}

function connLogError(provider, message) {
  const card = document.querySelector(
    `.conn-card[data-provider="${provider}"]`,
  );

  const log = card?.querySelector(".conn-log");

  if (log) {
    log.classList.remove("hidden");

    log.textContent = message;
  }
}

function runConnAction(provider, fn) {
  void fn().catch((err) => {
    connLogError(provider, err?.message || "Action failed");
  });
}

async function disconnectProvider(provider) {
  const card = document.querySelector(
    `.conn-card[data-provider="${provider}"]`,
  );

  const log = card?.querySelector(".conn-log");

  let res;

  try {
    res = await baklogFetch(`/api/auth/${provider}/disconnect`, {
      method: "POST",
    });
  } catch (_) {
    if (log) {
      log.classList.remove("hidden");

      log.textContent =
        "Could not reach the local server (is server.py running?).";
    }

    return;
  }

  if (!res.ok) {
    const data = await res.json().catch(() => ({}));

    if (log) {
      log.classList.remove("hidden");

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
  const card = document.querySelector(
    `.conn-card[data-provider="${provider}"]`,
  );

  const log = card?.querySelector(".conn-log");

  if (log) {
    log.classList.remove("hidden");

    log.textContent = "Checking for local data on this PC…";
  }

  let res;

  try {
    res = await baklogFetch(`/api/auth/${provider}/enable`, { method: "POST" });
  } catch (_) {
    if (log)
      log.textContent =
        "Could not reach the local server (is server.py running?).";

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

  if (log && provider === "amazon") {
    log.classList.remove("hidden");
    log.textContent =
      "Amazon launcher connected. Refresh the Amazon chip manually - launcher sources do not auto-fetch.";
  }
}

async function cancelBrowserConnect(provider) {
  try {
    const res = await baklogFetch(`/api/auth/${provider}/cancel`, {
      method: "POST",
    });
    const data = await res.json().catch(() => ({}));
    return res.ok && data.cancelled !== false;
  } catch {
    return false;
  }
}

function showConnectCancelControl(card, provider, log) {
  if (!card || !log) return;
  let cancelBtn = card.querySelector("[data-cancel-connect]");
  if (!cancelBtn) {
    cancelBtn = document.createElement("button");
    cancelBtn.type = "button";
    cancelBtn.className = "conn-disconnect";
    cancelBtn.dataset.cancelConnect = "1";
    cancelBtn.dataset.provider = provider;
    cancelBtn.title = "Cancel the in-progress sign-in window";
    cancelBtn.textContent = "Cancel sign-in";
    log.insertAdjacentElement("afterend", cancelBtn);
  }
  cancelBtn.hidden = false;
  cancelBtn.disabled = false;
}

function hideConnectCancelControl(card) {
  const cancelBtn = card?.querySelector("[data-cancel-connect]");
  if (cancelBtn) cancelBtn.hidden = true;
}

async function startBrowserConnect(provider) {
  const card = document.querySelector(
    `.conn-card[data-provider="${provider}"]`,
  );

  const log = card?.querySelector(".conn-log");
  const flowId = ++_connectFlowSeq;
  _connectFlowIds.set(provider, flowId);
  const isCurrentFlow = () => _connectFlowIds.get(provider) === flowId;
  const setLog = (text) => {
    if (log && isCurrentFlow()) log.textContent = text;
  };
  let es = null;
  // Time-box NetworkError spam for status/runs/fetchers polls while Connect
  // holds the HTTP thread (profile clear + Chromium launch). Refcounted +
  // auto-expires; each begin must end once (sibling Connects stay protected).
  beginConnectNetworkSuppress(120_000);
  let suppressEnded = false;
  const endSuppressOnce = () => {
    if (suppressEnded) return;
    suppressEnded = true;
    endConnectNetworkSuppress();
  };
  /** Release card-level state only while this flow still owns it. */
  const releaseSharedUi = () => {
    if (es && _activeConnectStreams.get(provider) === es) {
      _activeConnectStreams.delete(provider);
    }
    endSuppressOnce();
    if (!isCurrentFlow()) return;
    hideConnectCancelControl(card);
    stopPostConnectFastPoll();
  };

  // A "Reconnect" (status connected/expired) should start a clean sign-in:
  // wipe the old profile cookies server-side so a stale/expired session never
  // carries over. A first-time Connect has nothing to clear.
  // Epic library + wishlist keep their browser profiles on reconnect —
  // cf_clearance and storefront cookies must survive or Cloudflare re-challenges every time.
  const current = getAuthStatusSnapshot().find(
    (x) => x.key === provider,
  )?.status;
  const preserveProfile = provider === "epic" || provider === "epic_wishlist";
  const fresh =
    !preserveProfile && (current === "connected" || current === "expired");

  if (log) {
    log.classList.remove("hidden");

    log.textContent = fresh
      ? "Clearing old session, opening sign-in window…"
      : "Opening sign-in window…";
  }

  let res;

  try {
    res = await baklogFetch(
      `/api/auth/${provider}/start${fresh ? "?fresh=1" : ""}`,
      { method: "POST" },
    );
  } catch (err) {
    setLog("Could not reach the local server (is server.py running?).");
    endSuppressOnce();
    return;
  }

  let data = await res.json().catch(() => ({}));

  if (!res.ok) {
    const alreadyOpen = /already open/i.test(String(data.error || ""));
    if (alreadyOpen) {
      setLog(
        data.error ||
          "A sign-in window is already open. Cancelling so you can retry…",
      );
      if (isCurrentFlow()) showConnectCancelControl(card, provider, log);
      const cancelled = await cancelBrowserConnect(provider);
      if (cancelled) {
        setLog("Previous sign-in cancelled. Retrying…");
        if (isCurrentFlow()) hideConnectCancelControl(card);
        try {
          res = await baklogFetch(
            `/api/auth/${provider}/start${fresh ? "?fresh=1" : ""}`,
            { method: "POST" },
          );
          data = await res.json().catch(() => ({}));
        } catch {
          setLog("Could not reach the local server (is server.py running?).");
          endSuppressOnce();
          return;
        }
      }
    }
    if (!res.ok) {
      setLog(data.error || `Start failed (${res.status})`);
      endSuppressOnce();
      return;
    }
  }

  // A newer Connect click took over while this one was starting.
  if (!isCurrentFlow()) {
    endSuppressOnce();
    return;
  }

  showConnectCancelControl(card, provider, log);
  if (!data.session_id) {
    setLog("Connect start returned no session id.");
    releaseSharedUi();
    return;
  }
  startPostConnectFastPoll();

  const streamUrl = await urlWithStreamTicket(
    `/api/auth/${data.session_id}/stream`,
    { sessionId: data.session_id },
  );
  if (!isCurrentFlow()) {
    endSuppressOnce();
    return;
  }
  es = new EventSource(streamUrl);
  replaceActiveConnectStream(provider, es);
  let connectUiFinished = false;
  let transportErrorStreak = 0;

  const closeStream = () => {
    try {
      es.onerror = null;
      es.close();
    } catch (_) {
      /* noop */
    }
  };

  async function finishConnectUi() {
    if (connectUiFinished) return;
    connectUiFinished = true;
    closeStream();
    const owned = isCurrentFlow();
    releaseSharedUi();
    if (!owned) return;
    reconnectProviders.delete(provider);
    renderReconnectBanner();
    try {
      await refreshConnections();
      const row = getAuthStatusSnapshot().find((r) => r.key === provider);
      if (row?.status === "connected") setLog("Connected.");
    } catch (_) {
      /* noop */
    }
  }

  es.onerror = () => {
    if (connectUiFinished) return;
    // Browser retries while CONNECTING; only fail after a hard drop.
    if (es.readyState === EventSource.CONNECTING) {
      transportErrorStreak += 1;
      if (transportErrorStreak < 3) return;
    }
    setLog(
      "Sign-in stream dropped. Close the browser window and try Connect again.",
    );
    connectUiFinished = true;
    closeStream();
    releaseSharedUi();
  };

  es.addEventListener("waiting_for_user", (ev) => {
    try {
      const msg = JSON.parse(ev.data);
      setLog(msg.message || "Complete sign-in in the browser window…");
    } catch {
      setLog("Complete sign-in in the browser window…");
    }
  });

  es.addEventListener("status", (ev) => {
    try {
      const msg = JSON.parse(ev.data);
      if (msg.message) setLog(msg.message);
    } catch {
      /* ignore malformed status */
    }
  });

  es.addEventListener("signed_in", () => {
    setLog("Signed in - extracting credentials…");
  });

  es.addEventListener("extracted", () => {
    setLog("Connected.");
    void finishConnectUi();
  });

  es.addEventListener("error", (ev) => {
    let text;
    try {
      const msg = JSON.parse(ev.data);
      text = msg.message || "Sign-in failed";
    } catch {
      text = "Sign-in failed or window closed.";
    }

    // On frozen builds, the server console stderr may contain the actual
    // error details (e.g. a traceback from the connect callback).
    if (_serverFrozen) {
      text += " Check connect-*.log in your BAKLOG data folder (see Settings > Data folder).";
    }
    setLog(text);

    connectUiFinished = true;
    closeStream();
    releaseSharedUi();
  });

  es.addEventListener("done", () => {
    // Belt-and-suspenders: if the extracted event was dropped, still settle the
    // Connections card from the final auth/status poll on session end.
    void finishConnectUi();
  });
}

async function refreshBrowserPreflight() {
  try {
    const res = await baklogFetch("/api/config");
    if (!res.ok) return;
    const data = await res.json();
    if (typeof data.chromium_available === "boolean") {
      _chromiumAvailable = data.chromium_available;
    }
    if (typeof data.frozen === "boolean") {
      _serverFrozen = data.frozen;
    }
  } catch {
    // Older servers omit chromium_available — assume available.
  }
}

function renderBrowserWarn() {
  const el = document.getElementById("connBrowserWarn");
  if (!el) return;
  if (_chromiumAvailable) {
    el.hidden = true;
    el.classList.add("hidden");
    el.innerHTML = "";
    return;
  }
  el.innerHTML = `
    <div class="migration-banner-body">
      <span class="text-amber-400">No Chrome or Edge found. On first Connect, BAKLOG downloads a one-time browser (~150 MB), or install Google Chrome / Microsoft Edge.</span>
    </div>`;
  void import("./notice-toast.js").then(({ adoptNoticeToast }) => {
    adoptNoticeToast(el, { variant: "update" });
  });
}

export async function refreshConnections() {
  if (_connRefreshPromise) return _connRefreshPromise;
  _connRefreshInFlight = true;
  _connRefreshPromise = (async () => {
    try {
      await refreshBrowserPreflight();
      await fetchAuthStatus();

      clearConnRefreshError();

      renderConnections();
      renderBrowserWarn();

      renderReconnectBanner();

      const { applyItchTabVisibility } = await import("./filters-ui.js");
      applyItchTabVisibility();
    } catch (err) {
      const msg = connectionStatusErrorMessage(err);

      if (getAuthStatusSnapshot().length > 0) {
        renderConnections();

        showConnRefreshError(msg);
      } else {
        clearConnRefreshError();

        const rail = document.getElementById("connRail");

        const pane = document.getElementById("connPane");

        if (rail) rail.innerHTML = "";

        if (pane) {
          pane.innerHTML = `<p class="text-sm text-amber-400">${escapeHtml(msg)}</p>`;
        }
      }

      renderHero();
    } finally {
      _connRefreshInFlight = false;
      _connRefreshPromise = null;
    }
  })();
  return _connRefreshPromise;
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
  if (state.activeView !== "connections" || isPageHidden()) return;
  pollTimer = setInterval(() => {
    if (state.activeView !== "connections" || isPageHidden()) return;
    refreshConnections();
  }, 15000);
}

if (typeof document !== "undefined") {
  registerPausable({
    pause() {
      stopConnectionsPolling();
      if (postConnectFastPollTimer) {
        clearInterval(postConnectFastPollTimer);
        postConnectFastPollTimer = null;
      }
    },
    resume() {
      if (state.activeView === "connections") startConnectionsPolling();
      resumePostConnectFastPollIfActive();
    },
  });

  if (typeof BroadcastChannel !== "undefined") {
    try {
      const authChannel = new BroadcastChannel("baklog-auth");
      authChannel.onmessage = (ev) => {
        if (ev.data?.provider) refreshConnections();
      };
    } catch (_) {
      /* ignore */
    }
  }

  // Repaint the open Connections view the instant the auth-status cache changes
  // out-of-band (e.g. a fetcher run just failed with 401 and the fast path called
  // ingestAuthStatusProviders), instead of waiting up to 15s for the next poll.
  // Skip when our own refreshConnections() drove the update — it renders itself.
  document.addEventListener("baklog:auth-status", () => {
    if (_connRefreshInFlight) return;
    if (state.activeView !== "connections" || isPageHidden()) return;
    try {
      renderConnections();
      renderReconnectBanner();
    } catch (_) {
      /* view not mounted */
    }
  });
}

export function stopConnectionsPolling() {
  if (pollTimer) clearInterval(pollTimer);

  pollTimer = null;
}

bindCloudMirrorUi({ renderConnPrefs });

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

  const authish =
    /401|403|auth|cookie|session|credential|sign in|npsso|rejected/i.test(
      logText || "",
    );

  if (authish) showReconnectBanner([provider]);

  return authish;
}

/** Jump to Connections and start reconnect for a provider (browser auto-start). */
export async function reconnectProvider(provider, { autoStart = true } = {}) {
  if (!provider) return;

  document.querySelector('.view-tab[data-view="connections"]')?.click();
  await focusConnectionsProvider(provider);

  // When navigating in from a dashboard chip/affordance we only want to tab
  // over to the right card so the user can choose - never auto-open a sign-in
  // window or trigger a local scan. autoStart stays on for explicit in-page
  // connect actions (e.g. Steam onboarding button).
  if (!autoStart) return;

  const p = getAuthStatusSnapshot().find((x) => x.key === provider);

  const kind = p?.kind || "browser";

  if (kind === "local") {
    await enableLocalProvider(provider);
  } else if (kind === "browser") {
    await startBrowserConnect(provider);
  } else if (kind === "manual") {
    await openManualUrl(provider);
  }
}
