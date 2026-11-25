import { baklogFetch } from "./api-client.js";
import {
  getAccessToken,
  getAccountProfileId,
  isAccountAuthMode,
  proFeaturesUnlocked,
  refreshAccountPlan,
} from "./auth-gate.js";
import {
  capabilityStatus,
  getProSettings,
  setProSettings,
} from "./pro-capabilities.js";
import { escapeAttr, escapeHtml } from "./dom-util.js";
import { activeProfileId } from "./profiles.js";
import {
  describeImportScope,
  fetchMirrorSnapshot,
  formatLastUploadedBy,
  labelMirrorSourceProfile,
  listImportableArtifactPaths,
  preferMirrorSourceProfile,
  summarizeLocalUploadState,
} from "./cloud-mirror-status.js";

let _renderConnPrefs = () => {};

/** @param {{ renderConnPrefs: () => void }} deps */
export function bindCloudMirrorUi(deps) {
  _renderConnPrefs = deps.renderConnPrefs;
}

export function cloudMirrorPrefsVisible() {
  return (
    proFeaturesUnlocked() &&
    isAccountAuthMode() &&
    !!getAccessToken() &&
    capabilityStatus("cloud_sync_mirror") === "live"
  );
}

export function renderCloudMirrorPrefsDom() {
  const cloudStrip = document.getElementById("connCloudPrefs");
  const cloudWrap = document.getElementById("cloudMirrorToggleWrap");
  const cloudToggle = document.getElementById("cloudMirrorEnabledToggle");
  const syncBtn = document.getElementById("cloudMirrorSyncBtn");
  const importBtn = document.getElementById("cloudMirrorImportBtn");
  const clearBtn = document.getElementById("cloudMirrorClearBtn");
  const showCloudMirror = cloudMirrorPrefsVisible();
  if (cloudStrip) cloudStrip.hidden = !showCloudMirror;
  if (cloudWrap) cloudWrap.hidden = !showCloudMirror;
  if (syncBtn) {
    syncBtn.classList.toggle("hidden", !showCloudMirror);
    syncBtn.hidden = !showCloudMirror;
    syncBtn.disabled =
      !showCloudMirror || getProSettings().cloudMirrorEnabled !== true;
  }
  if (importBtn) {
    importBtn.classList.toggle("hidden", !showCloudMirror);
    importBtn.hidden = !showCloudMirror;
  }
  if (clearBtn) {
    clearBtn.classList.toggle("hidden", !showCloudMirror);
    clearBtn.hidden = !showCloudMirror;
  }
  if (cloudToggle && showCloudMirror) {
    cloudToggle.checked = getProSettings().cloudMirrorEnabled === true;
  }
}

let _cloudMirrorStatusRequest = 0;
const CLOUD_MIRROR_STATUS_HOLD_MS = 8000;
/** One-shot result line (e.g. after Clear) that the periodic status refresh must not blank. */
let _cloudMirrorStatusHold = null;

function holdCloudMirrorStatus(text, isError) {
  _cloudMirrorStatusHold = {
    text,
    isError,
    until: Date.now() + CLOUD_MIRROR_STATUS_HOLD_MS,
  };
  ++_cloudMirrorStatusRequest;
}

export async function refreshCloudMirrorUploadStatus() {
  const el = document.getElementById("cloudMirrorUploadStatus");
  if (!el) return;
  const showCloudMirror = cloudMirrorPrefsVisible();
  const hold = _cloudMirrorStatusHold;
  if (hold && Date.now() >= hold.until) _cloudMirrorStatusHold = null;
  if (showCloudMirror && _cloudMirrorStatusHold) {
    el.hidden = false;
    el.textContent = hold.text;
    el.classList.toggle("conn-prefs-note--error", hold.isError);
    return;
  }
  const enabled = getProSettings().cloudMirrorEnabled === true;
  if (!showCloudMirror || !enabled) {
    ++_cloudMirrorStatusRequest;
    el.hidden = true;
    el.textContent = "";
    el.classList.remove("conn-prefs-note--error");
    return;
  }
  const reqId = ++_cloudMirrorStatusRequest;
  try {
    const snap = await fetchMirrorSnapshot();
    if (reqId !== _cloudMirrorStatusRequest) return;
    const summary = summarizeLocalUploadState(snap.localUploadState);
    const by = formatLastUploadedBy(snap.localUploadState);
    el.hidden = false;
    el.textContent = by ? `${summary.line} ${by}` : summary.line;
    el.classList.toggle("conn-prefs-note--error", summary.kind === "error");
  } catch {
    if (reqId !== _cloudMirrorStatusRequest) return;
    el.hidden = false;
    el.textContent = "Could not read mirror upload status.";
    el.classList.remove("conn-prefs-note--error");
  }
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

function saveCloudMirrorEnabled(enabled) {
  return saveProSetting("cloudMirrorEnabled", enabled);
}

export async function handleCloudMirrorSyncNow() {
  const btn = document.getElementById("cloudMirrorSyncBtn");
  const statusEl = document.getElementById("cloudMirrorUploadStatus");
  _cloudMirrorStatusHold = null;
  if (btn) btn.disabled = true;
  try {
    const res = await baklogFetch("/api/mirror/sync", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    let data;
    try {
      data = await res.json();
    } catch {
      data = {};
    }
    if (!res.ok) {
      throw new Error(data.error || `Sync failed (${res.status})`);
    }
    const errors = Array.isArray(data.errors) ? data.errors : [];
    const uploaded =
      data.uploaded && typeof data.uploaded === "object" ? data.uploaded : {};
    const statuses = Object.values(uploaded);
    const okCount = statuses.filter((s) => s === "ok").length;
    const failCount = statuses.filter((s) => s !== "ok").length;
    const tooLargeCount = statuses.filter((s) => s === "too_large").length;
    if (statusEl) {
      statusEl.hidden = false;
      if (errors.length || failCount) {
        const first = errors[0]
          ? String(errors[0])
          : tooLargeCount
            ? `${tooLargeCount} file(s) over the size limit`
            : `${failCount} file(s) failed`;
        statusEl.textContent = `Mirror sync: ${okCount} ok, ${failCount || errors.length} failed. ${first}`;
        statusEl.classList.add("conn-prefs-note--error");
      } else if (!okCount && !(data.scheduled || []).length) {
        statusEl.textContent =
          "Nothing to sync yet - connect a store and fetch first.";
        statusEl.classList.remove("conn-prefs-note--error");
      } else {
        statusEl.textContent = `Mirror sync: ${okCount} file${okCount === 1 ? "" : "s"} uploaded.`;
        statusEl.classList.remove("conn-prefs-note--error");
      }
    }
    void refreshCloudMirrorUploadStatus();
  } catch (err) {
    if (statusEl) {
      statusEl.hidden = false;
      statusEl.textContent = err?.message || "Mirror sync failed.";
      statusEl.classList.add("conn-prefs-note--error");
    } else {
      window.alert(err?.message || "Mirror sync failed.");
    }
  } finally {
    _renderConnPrefs();
  }
}

export async function handleCloudMirrorToggle(ev) {
  const toggle = ev.target;
  const prev = !toggle.checked;
  try {
    toggle.disabled = true;
    if (toggle.checked) {
      const confirmed = window.confirm(
        [
          "Enable Cloud sync?",
          "",
          "This copies your library catalogs and personal statuses/notes from this PC into your BAKLOG account cloud storage.",
          "Anyone signed into your account can read that data on baklog.app/mirror.",
          "Store passwords, cookies, and secrets stay on this PC and are never uploaded.",
          "",
          "You can turn Cloud sync off later. New uploads stop, but existing cloud files remain until you use Clear cloud library (or delete them in account storage).",
          "",
          "Only continue if you understand you are exposing backlog data beyond this machine.",
        ].join("\n"),
      );
      if (!confirmed) {
        toggle.checked = false;
        return;
      }
    }
    await saveCloudMirrorEnabled(toggle.checked);
    _cloudMirrorStatusHold = null;
    _renderConnPrefs();
    void refreshCloudMirrorUploadStatus();
  } catch (err) {
    toggle.checked = prev;
    window.alert(err?.message || "Could not save cloud sync setting.");
  } finally {
    toggle.disabled = false;
  }
}

export async function handleCloudMirrorClear() {
  const btn = document.getElementById("cloudMirrorClearBtn");
  const statusEl = document.getElementById("cloudMirrorUploadStatus");
  const confirmed = window.confirm(
    [
      "Clear cloud library?",
      "",
      "This permanently deletes synced catalog and personal files from your BAKLOG account cloud storage for the current profile folder.",
      "Local library files on this PC are not deleted. Store passwords, cookies, and secrets stay on this PC.",
      "baklog.app/mirror will show an empty library until you Sync now again.",
      "",
      "This cannot be undone from BAKLOG.",
    ].join("\n"),
  );
  if (!confirmed) return;
  try {
    if (btn) btn.disabled = true;
    const res = await baklogFetch("/api/mirror/clear", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    let data;
    try {
      data = await res.json();
    } catch {
      data = {};
    }
    if (!res.ok) {
      throw new Error(data.error || `Clear failed (${res.status})`);
    }
    const count = Number(data.count || 0);
    holdCloudMirrorStatus(
      count > 0
        ? `Cloud library cleared (${count} file${count === 1 ? "" : "s"} deleted). Credentials stayed local.`
        : "Cloud library already empty.",
      false,
    );
  } catch (err) {
    if (statusEl) {
      holdCloudMirrorStatus(
        err?.message || "Could not clear cloud library.",
        true,
      );
    } else {
      window.alert(err?.message || "Could not clear cloud library.");
    }
  } finally {
    if (btn) btn.disabled = false;
    _renderConnPrefs();
  }
}

export async function openCloudMirrorImportDialog(initialSnap) {
  const dialog = document.getElementById("cloudMirrorImportDialog");
  const listEl = document.getElementById("cloudMirrorImportArtifactList");
  const personalToggle = document.getElementById("cloudMirrorImportPersonal");
  const intro = document.getElementById("cloudMirrorImportIntro");
  const sourceWrap = document.getElementById("cloudMirrorImportSourceWrap");
  const sourceSelect = document.getElementById("cloudMirrorImportSourceProfile");
  const modeOverwrite = document.getElementById("cloudMirrorImportModeOverwrite");
  const modeMerge = document.getElementById("cloudMirrorImportModeMerge");
  if (!dialog || !listEl || !personalToggle) return null;

  const accountId = getAccountProfileId() || "";
  const profiles = Array.isArray(initialSnap?.profiles) ? initialSnap.profiles : [];
  let sourceProfile =
    preferMirrorSourceProfile(profiles, {
      activeId: activeProfileId(),
      accountId,
    }) ||
    initialSnap?.profile ||
    activeProfileId();
  let importableCount = 0;
  let lastScope = [];

  const selectedMode = () =>
    modeMerge?.checked ? "merge" : "overwrite";

  const updateIntro = () => {
    if (!intro) return;
    const sourceLabel = labelMirrorSourceProfile(sourceProfile, { accountId });
    const scopeText = lastScope.length ? ` (${lastScope.join(", ")})` : "";
    if (selectedMode() === "merge") {
      intro.textContent =
        `Merges cloud folder "${sourceLabel}" into the current local profile${scopeText}. ` +
        "Remote wins on overlapping game/status keys; local-only rows stay. " +
        "Store credentials are not copied - reconnect stores afterward.";
    } else {
      intro.textContent =
        `Replaces matching files in the current local profile from cloud folder "${sourceLabel}"${scopeText}. ` +
        "Store credentials are not copied - reconnect stores afterward.";
    }
  };

  const fillPaths = (artifacts) => {
    const paths = listImportableArtifactPaths(artifacts);
    importableCount = paths.length;
    lastScope = describeImportScope(paths);
    updateIntro();
    listEl.innerHTML = paths.length
      ? paths.map((path) => `<li>${escapeHtml(path)}</li>`).join("")
      : "<li>No importable files in this cloud profile.</li>";
    personalToggle.checked = paths.includes("data/personal.json");
    personalToggle.disabled = !paths.includes("data/personal.json");
    return paths;
  };

  let artifacts = initialSnap?.artifacts || [];
  if (sourceProfile && String(initialSnap?.profile || "") !== sourceProfile) {
    try {
      const preferred = await fetchMirrorSnapshot(sourceProfile);
      artifacts = preferred.artifacts;
    } catch {
      artifacts = [];
    }
  }
  fillPaths(artifacts);
  if (!importableCount && profiles.length <= 1) return null;

  if (modeOverwrite) modeOverwrite.onchange = updateIntro;
  if (modeMerge) modeMerge.onchange = updateIntro;

  if (sourceWrap && sourceSelect) {
    if (profiles.length > 1) {
      sourceSelect.innerHTML = profiles
        .map((pid) => {
          const label = labelMirrorSourceProfile(pid, { accountId });
          const selected = pid === sourceProfile ? " selected" : "";
          return `<option value="${escapeAttr(pid)}"${selected}>${escapeHtml(label)}</option>`;
        })
        .join("");
      sourceWrap.hidden = false;
      sourceWrap.classList.remove("hidden");
      sourceSelect.onchange = async () => {
        sourceProfile = sourceSelect.value;
        try {
          const next = await fetchMirrorSnapshot(sourceProfile);
          fillPaths(next.artifacts);
        } catch (err) {
          importableCount = 0;
          listEl.innerHTML = `<li>${escapeHtml(err?.message || "Could not list this cloud profile.")}</li>`;
          personalToggle.checked = false;
          personalToggle.disabled = true;
        }
      };
    } else {
      sourceWrap.hidden = true;
      sourceWrap.classList.add("hidden");
      sourceSelect.onchange = null;
    }
  }

  if (!importableCount && profiles.length <= 1) return null;

  // Default mode is overwrite each open (canceling with Merge selected must not stick).
  if (modeOverwrite) {
    modeOverwrite.checked = true;
    modeOverwrite.onchange = updateIntro;
  }
  if (modeMerge) {
    modeMerge.checked = false;
    modeMerge.onchange = updateIntro;
  }
  updateIntro();

  dialog.returnValue = "cancel";
  dialog.showModal();
  return new Promise((resolve) => {
    dialog.addEventListener(
      "close",
      () => {
        if (sourceSelect) sourceSelect.onchange = null;
        if (modeOverwrite) modeOverwrite.onchange = null;
        if (modeMerge) modeMerge.onchange = null;
        resolve({
          confirmed: dialog.returnValue === "confirm" && importableCount > 0,
          includePersonal: personalToggle.checked,
          sourceProfile,
          mode: selectedMode(),
        });
      },
      { once: true },
    );
  });
}

export async function handleCloudMirrorImport() {
  const btn = document.getElementById("cloudMirrorImportBtn");
  try {
    if (btn) btn.disabled = true;
    const snap = await fetchMirrorSnapshot();
    const choice = await openCloudMirrorImportDialog(snap);
    if (!choice?.confirmed) return;

    const { importFromCloudMirror } = await import("./cloud-mirror-import.js");
    const result = await importFromCloudMirror({
      includePersonal: choice.includePersonal,
      sourceProfile: choice.sourceProfile || undefined,
      mode: choice.mode === "merge" ? "merge" : "overwrite",
    });
    const count = result?.count ?? 0;
    const imported = Array.isArray(result?.imported)
      ? result.imported.join(", ")
      : "";
    const modeLabel = result?.mode === "merge" ? "Merge" : "Replace";
    window.alert(
      `Cloud sync import complete (${modeLabel}, ${count} file${count === 1 ? "" : "s"}).${imported ? `\n\n${imported}` : ""}\n\nThe app will reload.`,
    );
    window.location.reload();
  } catch (err) {
    window.alert(err?.message || "Cloud mirror import failed.");
  } finally {
    if (btn) btn.disabled = false;
  }
}