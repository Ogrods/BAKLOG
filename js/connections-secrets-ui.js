import { baklogFetch } from "./api-client.js";

export function wireMasterPasswordSave() {
  const btn = document.getElementById("masterPasswordSave");

  if (!btn || btn.dataset.bound === "1") return;

  btn.dataset.bound = "1";

  btn.addEventListener("click", async () => {
    const pw = document.getElementById("masterPasswordInput")?.value || "";

    try {
      const res = await baklogFetch("/api/auth/master-password", {
        method: "POST",

        headers: { "Content-Type": "application/json" },

        body: JSON.stringify({ password: pw || null }),
      });

      const hint = document.getElementById("masterPasswordHint");

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));

        if (hint)
          hint.textContent = data.error || `Save failed (${res.status})`;

        return;
      }

      if (hint)
        hint.textContent = pw
          ? "Master password set (portable encryption)."
          : "Using OS keychain.";
    } catch (_) {
      const hint = document.getElementById("masterPasswordHint");

      if (hint) hint.textContent = "Could not reach the local server.";
    }
  });
}

function setSecretsBundleHint(text, isError = false) {
  const hint = document.getElementById("secretsBundleHint");
  if (!hint) return;
  hint.textContent = text || "";
  hint.classList.toggle("text-red-400", !!isError);
  hint.classList.toggle("text-slate-400", !isError);
}

function promptSecretsBundlePassphrase({ mode = "export" } = {}) {
  return new Promise((resolve) => {
    const dialog = document.getElementById("secretsBundleDialog");
    const form = document.getElementById("secretsBundleDialogForm");
    const title = document.getElementById("secretsBundleDialogTitle");
    const help = document.getElementById("secretsBundleDialogHelp");
    const pw = document.getElementById("secretsBundlePassphrase");
    const confirmWrap = document.getElementById("secretsBundleConfirmWrap");
    const confirmPw = document.getElementById("secretsBundlePassphraseConfirm");
    const cancelBtn = document.getElementById("secretsBundleCancel");
    if (!dialog || !form || !pw) {
      resolve(null);
      return;
    }
    const isExport = mode === "export";
    if (title)
      title.textContent = isExport
        ? "Export bundle passphrase"
        : "Import bundle passphrase";
    if (help) {
      help.textContent = isExport
        ? "Choose a passphrase for this backup file. You will need it to import on another machine."
        : "Enter the passphrase you used when exporting this bundle.";
    }
    pw.value = "";
    if (confirmPw) confirmPw.value = "";
    if (confirmWrap) confirmWrap.classList.toggle("hidden", !isExport);
    const cleanup = () => {
      form.removeEventListener("submit", onSubmit);
      cancelBtn?.removeEventListener("click", onCancel);
      dialog.removeEventListener("close", onClose);
    };
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      cleanup();
      if (dialog.open) dialog.close();
      resolve(value);
    };
    const onCancel = (ev) => {
      ev.preventDefault();
      finish(null);
    };
    const onClose = () => {
      finish(null);
    };
    const onSubmit = (ev) => {
      ev.preventDefault();
      const value = pw.value || "";
      if (value.length < 8) {
        setSecretsBundleHint("Passphrase must be at least 8 characters.", true);
        return;
      }
      if (isExport && confirmPw && value !== confirmPw.value) {
        setSecretsBundleHint("Passphrases do not match.", true);
        return;
      }
      finish(value);
    };
    form.addEventListener("submit", onSubmit);
    cancelBtn?.addEventListener("click", onCancel);
    dialog.addEventListener("close", onClose);
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.removeAttribute("hidden");
    pw.focus();
  });
}

async function exportSecretsBundle() {
  const passphrase = await promptSecretsBundlePassphrase({ mode: "export" });
  if (!passphrase) return;
  setSecretsBundleHint("Exporting bundle…");
  try {
    const resp = await baklogFetch("/api/auth/secrets/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ passphrase, include_profiles: true }),
    });
    if (!resp.ok) {
      let msg = `Export failed (${resp.status})`;
      try {
        const err = await resp.json();
        if (err?.error) msg = err.error;
      } catch (_) {
        /* binary or empty */
      }
      setSecretsBundleHint(msg, true);
      return;
    }
    const blob = await resp.blob();
    const cd = resp.headers.get("Content-Disposition") || "";
    const match = cd.match(/filename="([^"]+)"/);
    const filename = match?.[1] || "baklog-secrets.bundle";
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    setSecretsBundleHint(
      "Bundle downloaded. Store it somewhere safe - we cannot recover the passphrase.",
    );
  } catch (err) {
    setSecretsBundleHint(err?.message || "Export failed.", true);
  }
}

async function importSecretsBundle(file) {
  if (!file) return;
  const passphrase = await promptSecretsBundlePassphrase({ mode: "import" });
  if (!passphrase) return;
  setSecretsBundleHint("Importing bundle…");
  try {
    const buf = await file.arrayBuffer();
    const bytes = new Uint8Array(buf);
    let binary = "";
    const chunk = 0x8000;
    for (let i = 0; i < bytes.length; i += chunk) {
      binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
    }
    const blobB64 = btoa(binary);
    const resp = await baklogFetch("/api/auth/secrets/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ passphrase, blob: blobB64 }),
    });
    const payload = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      setSecretsBundleHint(
        payload?.error || `Import failed (${resp.status})`,
        true,
      );
      return;
    }
    const nProv = (payload.providers_imported || []).length;
    const nProf = (payload.profiles_imported || []).length;
    setSecretsBundleHint(
      `Imported ${nProv} provider(s) and ${nProf} profile(s). Reloading…`,
    );
    window.setTimeout(() => window.location.reload(), 1200);
  } catch (err) {
    setSecretsBundleHint(err?.message || "Import failed.", true);
  }
}

export function wireSecretsBundle() {
  const exportBtn = document.getElementById("secretsExportBtn");
  const importBtn = document.getElementById("secretsImportBtn");
  const importFile = document.getElementById("secretsImportFile");
  if (!exportBtn || !importBtn || !importFile) return;
  if (exportBtn.dataset.bound === "1") return;
  exportBtn.dataset.bound = "1";
  importBtn.dataset.bound = "1";
  exportBtn.addEventListener("click", () => {
    exportSecretsBundle();
  });
  importBtn.addEventListener("click", () => {
    importFile.value = "";
    importFile.click();
  });
  importFile.addEventListener("change", () => {
    const file = importFile.files?.[0];
    if (file) importSecretsBundle(file);
  });
}