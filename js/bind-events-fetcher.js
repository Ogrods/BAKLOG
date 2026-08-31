import { state } from './state.js';
import { savePrefs } from './prefs.js';
import {
  fetcherRunner,
  renderDashboardFetcherHealth,
  toggleLegendTips,
  formatRefreshIntervalLabel,
  primaryFailureNavigateTarget,
  dismissStickyFailedState,
} from './fetcher-health.js';
import { pendingForEnrich } from './fetcher/source-meta.js';
import {
  confirmHltbEstimate,
  shouldConfirmHltbRun,
} from './hltb-estimate-modal.js';
import { reconnectProvider } from './connections.js';

/** @internal Vitest + bind-events entry for global status pill clicks. */
export function handleGlobalStatusClick(e) {
  const pill = document.getElementById('fetcherGlobalStatus');
  if (!pill) return;
  if (e.shiftKey) {
    fetcherRunner.openFetcherLog({ focusPanel: false });
    return;
  }
  const isFailed = pill.classList.contains('fh-global-status-failed');
  // Capture navigate target before clearing sticky failed (map drives routing).
  const navTarget = isFailed ? primaryFailureNavigateTarget() : null;
  if (isFailed) {
    // Always clear — otherwise a red pill with an already-connected provider
    // (or a non-auth failure) stays red and bricks subsequent fetcher UI.
    dismissStickyFailedState({ all: true });
  }
  if (navTarget) {
    fetcherRunner.hideFetcherPopover();
    void reconnectProvider(navTarget.provider, { autoStart: false });
    return;
  }
  fetcherRunner.openFetcherLog({ focusPanel: false });
}

/**
 * Wire every fetcher-health surface: the dashboard health panel toggles/sliders,
 * the bottom fetcher bar + popover, the log launcher, and the deep-sync hook.
 *
 * Extracted from bind-events.js so that file stays a thin orchestrator (and so
 * the fetcher-health DOM wiring lives next to the module it drives). Called once
 * from bindEvents().
 */
export function bindFetcherHealthEvents() {
  document.getElementById("dashboardFetcherHealth")?.addEventListener("change", e => {
    if (e.target.id === "fetcherHealthShowConnected") {
      state.prefs.fetcherHealthShowConnected = e.target.checked;
      savePrefs();
      renderDashboardFetcherHealth();
    } else if (e.target.id === "fetcherHealthShowStaleMissing") {
      state.prefs.fetcherHealthShowStaleMissing = e.target.checked;
      savePrefs();
      renderDashboardFetcherHealth();
    } else if (e.target.id === "itadAutoRefreshToggle") {
      state.prefs.itadAutoRefreshDisabled = !e.target.checked;
      const slider = document.getElementById("itadAutoRefreshInterval");
      if (slider) slider.disabled = !e.target.checked;
      savePrefs();
    } else if (e.target.id === "itadAutoRefreshInterval") {
      state.prefs.itadAutoRefreshIntervalMin = Number(e.target.value);
      savePrefs();
    } else if (e.target.id === "claimsAutoRefreshToggle") {
      state.prefs.claimsAutoRefreshDisabled = !e.target.checked;
      const slider = document.getElementById("claimsAutoRefreshInterval");
      if (slider) slider.disabled = !e.target.checked;
      savePrefs();
    } else if (e.target.id === "claimsAutoRefreshInterval") {
      state.prefs.claimsAutoRefreshIntervalMin = Number(e.target.value);
      savePrefs();
    } else if (e.target.id === "autoEnrichOnAddToggle") {
      state.prefs.autoEnrichOnAdd = e.target.checked;
      savePrefs();
    }
  });

  document.getElementById("dashboardFetcherHealth")?.addEventListener("input", e => {
    if (e.target.id === "itadAutoRefreshInterval") {
      const valEl = document.getElementById("itadAutoRefreshIntervalVal");
      if (valEl) valEl.textContent = `${e.target.value}m`;
    } else if (e.target.id === "claimsAutoRefreshInterval") {
      const valEl = document.getElementById("claimsAutoRefreshIntervalVal");
      if (valEl) valEl.textContent = formatRefreshIntervalLabel(e.target.value);
    }
  });

  document.getElementById("dashboardFetcherHealth")?.addEventListener("click", e => {
    const legendToggle = e.target.closest("[data-role=\"fh-legend-toggle\"]");
    if (legendToggle) {
      e.preventDefault();
      toggleLegendTips();
      return;
    }
    const staleBtn = e.target.closest(".fh-run-stale");
    // matches(':disabled') covers attribute + property; happy-dom can fire
    // programmatic clicks on disabled buttons under Vitest 4.
    if (staleBtn && !staleBtn.matches(":disabled")) {
      e.preventDefault();
      fetcherRunner.runAllStale();
      return;
    }
    const failedBtn = e.target.closest(".fh-run-failed");
    if (failedBtn && !failedBtn.matches(":disabled")) {
      e.preventDefault();
      fetcherRunner.runAllFailed();
      return;
    }
    const chip = e.target.closest(".fh-chip[data-fetcher-key]");
    if (!chip) return;
    if (chip.dataset.fetcherConnect) {
      e.preventDefault();
      fetcherRunner.hideFetcherPopover();
      dismissStickyFailedState({
        fetcherKey: chip.dataset.fetcherKey,
        provider: chip.dataset.fetcherConnect,
      });
      reconnectProvider(chip.dataset.fetcherConnect, { autoStart: false });
      return;
    }
    if (chip.disabled) return;
    e.preventDefault();
    const key = chip.dataset.fetcherKey;
    const refresh = e.shiftKey;
    if (key === 'hltb') {
      const pending = pendingForEnrich('hltb');
      if (shouldConfirmHltbRun(pending, { refresh })) {
        void confirmHltbEstimate(pending, { refresh }).then((ok) => {
          if (ok) fetcherRunner.run(key, { refresh });
        });
        return;
      }
    }
    fetcherRunner.run(key, { refresh });
  });

  // Pro-only deep achievement/trophy sync: re-pull the store's achievement data.
  document.addEventListener("baklog:deep-sync", async (e) => {
    const store = e.detail?.store;
    if (store !== "psn" && store !== "xbox") return;
    await fetcherRunner.run(store, { refresh: true });
  });

  document.getElementById("fetcherPopoverBackdrop")?.addEventListener("click", () => {
    fetcherRunner.hideFetcherPopover();
  });
  document.querySelectorAll("[data-fetcher-popover-close]").forEach(btn => {
    btn.addEventListener("click", () => fetcherRunner.hideFetcherPopover());
  });
  document.getElementById("fetcherRow")?.addEventListener("click", e => {
    if (e.target.closest(".fh-chip, .fh-run-stale, .fh-run-failed, .fh-toggle, .fh-log, .fh-head-actions label")) {
      return;
    }
    const toggleBtn = e.target.closest("[data-role='bar-toggle']");
    if (toggleBtn) {
      e.preventDefault();
      e.stopPropagation();
      fetcherRunner.toggleFetcherPanel({ manual: true });
      return;
    }
    const bar = e.target.closest("[data-role='fetcher-bar']");
    if (bar && document.getElementById("fetcherRow")?.classList.contains("is-collapsed")) {
      e.preventDefault();
      fetcherRunner.showFetcherPopover();
    }
  });
  document.getElementById("showFetcherLog")?.addEventListener("click", () => {
    document.getElementById("kebabMenu")?.classList.remove("open");
    fetcherRunner.openFetcherLog();
  });
  document.getElementById("fetcherGlobalStatus")?.addEventListener("click", (e) => {
    handleGlobalStatusClick(e);
  });
  document.getElementById("fetcherStatLayoutToggle")?.addEventListener("click", () => {
    fetcherRunner.cycleStatLayout();
  });
}
