/** Bug report consent dialog — open, send, copy, cancel, event wiring. */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Window } from "happy-dom";

vi.mock("../js/error-boundary.js", async (importOriginal) => {
  const actual = await importOriginal();
  const bundle = {
    bundle: "baklog-bug-bundle",
    app_version: "test",
    errors: { session: [], persisted: [], session_count: 0, persisted_count: 0 },
    runtime: { view: "library" },
    server: null,
  };
  return {
    ...actual,
    buildBugBundle: vi.fn(() => bundle),
    buildBugBundleAsync: vi.fn(async () => bundle),
    copyBugBundleToClipboard: vi.fn(async () => true),
    submitBugReport: vi.fn(async () => ({ ok: true })),
  };
});

describe("bug report dialog", () => {
  let openBugReportDialog;
  let closeBugReportDialog;
  let initBugReportDialog;
  let copyBugBundleToClipboard;
  let submitBugReport;

  beforeEach(async () => {
    const win = new Window({ url: "http://127.0.0.1:8765/" });
    global.window = win;
    global.document = win.document;
    global.localStorage = win.localStorage;
    document.body.innerHTML = "";

    vi.resetModules();
    ({
      openBugReportDialog,
      closeBugReportDialog,
      initBugReportDialog,
    } = await import("../js/bug-report.js"));
    ({
      copyBugBundleToClipboard,
      submitBugReport,
    } = await import("../js/error-boundary.js"));
  });

  afterEach(() => {
    delete global.window;
    delete global.document;
    delete global.localStorage;
    vi.clearAllMocks();
  });

  it("opens the dialog and shows a payload preview", async () => {
    openBugReportDialog();
    const modal = document.getElementById("bugReportModal");
    expect(modal).toBeTruthy();
    expect(modal.classList.contains("flex")).toBe(true);
    const preview = document.getElementById("bugReportPreview");
    await vi.waitFor(() => {
      expect(preview.textContent).toContain("baklog-bug-bundle");
    });
  });

  it("closes on Cancel", () => {
    openBugReportDialog();
    document.querySelector('[data-action="cancel"]')?.click();
    const modal = document.getElementById("bugReportModal");
    expect(modal.classList.contains("hidden")).toBe(true);
  });

  it("Copy instead calls copyBugBundleToClipboard", async () => {
    openBugReportDialog();
    document.querySelector('[data-action="copy"]')?.click();
    await Promise.resolve();
    expect(copyBugBundleToClipboard).toHaveBeenCalledTimes(1);
    expect(submitBugReport).not.toHaveBeenCalled();
  });

  it("Send report calls submitBugReport with contact and note", async () => {
    openBugReportDialog();
    document.getElementById("bugReportContact").value = "tester@example.com";
    document.getElementById("bugReportNote").value = "Clicked refresh";
    document.querySelector('[data-action="send"]')?.click();
    await vi.waitFor(() => expect(submitBugReport).toHaveBeenCalledTimes(1));
    expect(submitBugReport).toHaveBeenCalledWith({
      contact: "tester@example.com",
      note: "Clicked refresh",
    });
  });

  it("baklog:open-bug-report event opens the dialog when initBugReportDialog is wired", () => {
    initBugReportDialog();
    window.dispatchEvent(new CustomEvent("baklog:open-bug-report"));
    expect(document.getElementById("bugReportModal")?.classList.contains("flex")).toBe(true);
  });

  it("closeBugReportDialog hides an open dialog", () => {
    openBugReportDialog();
    closeBugReportDialog();
    expect(document.getElementById("bugReportModal")?.classList.contains("hidden")).toBe(true);
  });
});
