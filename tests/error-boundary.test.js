/**
 * Error-boundary + bug-bundle tests.
 *
 * Three angles:
 *   1. record() / persistence — uncaught errors land in the in-memory list
 *      AND the localStorage ring; the ring is capped at MAX_PERSISTED.
 *   2. buildBugBundle() shape — whitelist contract. The bundle includes the
 *      app context fields we documented in PRIVACY.md and NEVER references
 *      personal / library / credential surfaces (paranoia check on the
 *      serialized payload).
 *   3. registerBugBundleContext — injected lookups land in the bundle.
 *
 * NOTE: error-boundary.js holds module-level state (_errors, _persistedRing).
 * Tests reset between cases via _resetForTests() and reinstall the window
 * fixture so each case sees a clean tab. The module is imported once at the
 * top because vitest+vite doesn't support cache-busting dynamic imports.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Window } from "happy-dom";
import {
  _resetForTests,
  buildBugBundle,
  BUG_REPORT_ENDPOINT,
  getBugReportEndpoint,
  getCapturedErrors,
  installGlobalErrorHandler,
  registerBugBundleContext,
  reportError,
  submitBugReport,
} from "../js/error-boundary.js";

function installWindow({ versionMeta = "9.9.9-test", localStorageRaw } = {}) {
  const win = new Window({ url: "http://127.0.0.1:8765/" });
  global.window = win;
  global.document = win.document;
  global.navigator = win.navigator;
  global.localStorage = win.localStorage;
  if (versionMeta) {
    const meta = win.document.createElement("meta");
    meta.setAttribute("name", "baklog-version");
    meta.setAttribute("content", versionMeta);
    win.document.head.appendChild(meta);
  }
  if (localStorageRaw !== undefined) {
    win.localStorage.setItem("baklog-error-log", localStorageRaw);
  }
  return win;
}

function teardownWindow() {
  delete global.window;
  delete global.document;
  delete global.navigator;
  delete global.localStorage;
}

describe("error-boundary persistence", () => {
  beforeEach(() => {
    installWindow();
    _resetForTests();
  });
  afterEach(() => { teardownWindow(); });

  it("record() persists each entry to localStorage ring", () => {
    reportError(new Error("boom one"));
    reportError(new Error("boom two"));
    const raw = window.localStorage.getItem("baklog-error-log");
    const parsed = JSON.parse(raw);
    expect(Array.isArray(parsed)).toBe(true);
    expect(parsed.length).toBe(2);
    expect(parsed[0].message).toBe("boom one");
    expect(parsed[1].message).toBe("boom two");
  });

  it("persisted ring is capped at MAX_PERSISTED (200)", () => {
    // Each entry needs a different signature so dedupe doesn't drop them.
    for (let i = 0; i < 210; i += 1) {
      reportError(new Error(`unique-${i}`));
    }
    const parsed = JSON.parse(window.localStorage.getItem("baklog-error-log"));
    expect(parsed.length).toBe(200);
    expect(parsed[0].message).toBe("unique-10");
    expect(parsed[199].message).toBe("unique-209");
  });

  it("persisted ring truncates long stacks; session keeps full stack", () => {
    const longStack = "x".repeat(10_000);
    const err = new Error("big stack");
    err.stack = longStack;
    reportError(err);
    const session = getCapturedErrors();
    expect(session[0].stack.length).toBe(10_000);
    const persisted = JSON.parse(window.localStorage.getItem("baklog-error-log"));
    expect(persisted[0].stack.length).toBeLessThanOrEqual(4096 + 30);
    expect(persisted[0].stack).toContain("(... truncated for storage)");
    expect(persisted[0].stack).not.toBe(longStack);
  });

  it("deduped errors within the window bump repeats instead of adding rows", () => {
    const err = new Error("same bug");
    reportError(err);
    reportError(err);
    expect(getCapturedErrors().length).toBe(1);
    expect(getCapturedErrors()[0].repeats).toBe(2);
    const persisted = JSON.parse(window.localStorage.getItem("baklog-error-log"));
    expect(persisted.length).toBe(1);
    expect(persisted[0].repeats).toBe(2);
  });
});

describe("error-boundary rehydration", () => {
  afterEach(() => { teardownWindow(); });

  it("installGlobalErrorHandler rehydrates persisted ring from localStorage", () => {
    const seeded = JSON.stringify([
      { kind: "reported", time: 1, message: "from a prior session", stack: "", source: "", lineno: 0, colno: 0, name: "Error" },
    ]);
    installWindow({ localStorageRaw: seeded });
    _resetForTests();
    // Re-seed because _resetForTests clears storage.
    window.localStorage.setItem("baklog-error-log", seeded);
    installGlobalErrorHandler();
    const bundle = buildBugBundle();
    expect(bundle.errors.persisted.length).toBe(1);
    expect(bundle.errors.persisted[0].message).toBe("from a prior session");
  });

  it("corrupt localStorage raw payload is silently ignored", () => {
    installWindow();
    _resetForTests();
    window.localStorage.setItem("baklog-error-log", "{not valid json");
    installGlobalErrorHandler();
    const bundle = buildBugBundle();
    expect(bundle.errors.persisted).toEqual([]);
  });

  it("prunes stale and ignored entries from persisted ring on install", () => {
    const seeded = JSON.stringify([
      { kind: "error", time: 1, message: "ResizeObserver loop completed with undelivered notifications.", stack: "", source: "", lineno: 0, colno: 0, name: "Error" },
      { kind: "unhandledrejection", time: 2, message: "authStatus is not defined", stack: "", source: "", lineno: 0, colno: 0, name: "ReferenceError" },
      { kind: "reported", time: 3, message: "still relevant", stack: "", source: "", lineno: 0, colno: 0, name: "Error" },
    ]);
    installWindow({ localStorageRaw: seeded });
    _resetForTests();
    window.localStorage.setItem("baklog-error-log", seeded);
    installGlobalErrorHandler();
    const bundle = buildBugBundle();
    expect(bundle.errors.persisted.length).toBe(1);
    expect(bundle.errors.persisted[0].message).toBe("still relevant");
    const stored = JSON.parse(window.localStorage.getItem("baklog-error-log"));
    expect(stored.length).toBe(1);
    expect(stored[0].message).toBe("still relevant");
  });
});

describe("error-boundary ignored noise", () => {
  beforeEach(() => {
    installWindow();
    _resetForTests();
    installGlobalErrorHandler();
  });
  afterEach(() => { teardownWindow(); });

  it("does not capture ResizeObserver loop warnings", () => {
    reportError(new Error("ResizeObserver loop completed with undelivered notifications."));
    expect(getCapturedErrors().length).toBe(0);
    expect(window.localStorage.getItem("baklog-error-log")).toBeNull();
    const bundle = buildBugBundle();
    expect(bundle.errors.session.length).toBe(0);
    expect(bundle.errors.persisted.length).toBe(0);
  });
});

describe("buildBugBundle shape", () => {
  beforeEach(() => {
    installWindow({ versionMeta: "9.9.9-test" });
    _resetForTests();
  });
  afterEach(() => { teardownWindow(); });

  it("includes app context + error arrays", () => {
    reportError(new Error("xyz"));
    const bundle = buildBugBundle();
    expect(bundle.bundle).toBe("baklog-bug-bundle");
    expect(bundle.bundle_version).toBe(2);
    expect(bundle.app_version).toBe("9.9.9-test");
    expect(typeof bundle.generated_at).toBe("string");
    expect(new Date(bundle.generated_at).toString()).not.toBe("Invalid Date");
    expect(typeof bundle.ua).toBe("string");
    expect(bundle.ua.length).toBeLessThanOrEqual(256);
    expect(bundle.runtime).toBeDefined();
    expect(bundle.errors.session.length).toBe(1);
    expect(bundle.errors.session[0].message).toBe("xyz");
    expect(typeof bundle.notice).toBe("string");
  });

  it("app_version falls back to 'unknown' when meta tag is missing", () => {
    // Tear down + re-init without the meta tag.
    teardownWindow();
    installWindow({ versionMeta: null });
    _resetForTests();
    const bundle = buildBugBundle();
    expect(bundle.app_version).toBe("unknown");
  });

  it("registerBugBundleContext injects fingerprint + filter count", () => {
    registerBugBundleContext({
      getFingerprint: () => "fp-abc-123",
      getActiveFilterCount: () => 4,
    });
    const bundle = buildBugBundle();
    expect(bundle.runtime.table_fingerprint).toBe("fp-abc-123");
    expect(bundle.runtime.active_filter_count).toBe(4);
  });

  it("registerBugBundleContext tolerates a throwing lookup", () => {
    registerBugBundleContext({
      getFingerprint: () => { throw new Error("nope"); },
      getActiveFilterCount: () => { throw new Error("also nope"); },
    });
    const bundle = buildBugBundle();
    expect(bundle.runtime.table_fingerprint).toBe(null);
    expect(bundle.runtime.active_filter_count).toBe(null);
  });

  it("PARANOIA: serialized bundle does NOT contain personal/library/credential keys", () => {
    // Poison the page with PII-shaped data to confirm the bundle's whitelist
    // build path can't accidentally leak it through stack traces or otherwise.
    window.state = {
      personal: { "steam:730": { notes: "SECRET_NOTE_DO_NOT_LEAK", status: "playing" } },
      manualGames: [{ title: "SECRET_MANUAL_GAME" }],
      gamesBySource: { steam: [{ id: 1, name: "SECRET_LIBRARY_TITLE" }] },
    };
    window.__credentials = { STEAM_API_KEY: "SECRET_KEY_DO_NOT_LEAK" };
    reportError(new Error("user-facing error"));
    const serialized = JSON.stringify(buildBugBundle());
    expect(serialized).not.toContain("SECRET_NOTE_DO_NOT_LEAK");
    expect(serialized).not.toContain("SECRET_MANUAL_GAME");
    expect(serialized).not.toContain("SECRET_LIBRARY_TITLE");
    expect(serialized).not.toContain("SECRET_KEY_DO_NOT_LEAK");
    expect(serialized).not.toMatch(/STEAM_API_KEY/);
    expect(serialized).not.toMatch(/state\.personal/);
    expect(serialized).not.toMatch(/manualGames/);
    expect(serialized).not.toMatch(/gamesBySource/);
  });

  it("PARANOIA: bundle keys are exactly the documented whitelist", () => {
    const bundle = buildBugBundle();
    const topLevel = Object.keys(bundle).sort();
    expect(topLevel).toEqual([
      "app_version",
      "bundle",
      "bundle_version",
      "errors",
      "generated_at",
      "notice",
      "runtime",
      "ua",
    ]);
    const runtimeKeys = Object.keys(bundle.runtime).sort();
    expect(runtimeKeys).toEqual([
      "active_filter_count",
      "dash_stats",
      "data_version",
      "last_render_ms",
      "table_fingerprint",
      "view",
    ]);
    const errorKeys = Object.keys(bundle.errors).sort();
    expect(errorKeys).toEqual([
      "persisted",
      "persisted_count",
      "session",
      "session_count",
    ]);
  });
});

describe("submitBugReport", () => {
  /** @type {import('vitest').Mock} */
  let fetchMock;

  beforeEach(() => {
    installWindow({ versionMeta: "9.9.9-test" });
    _resetForTests();
    fetchMock = vi.fn(async () => ({
      ok: true,
      json: async () => ({ ok: true }),
    }));
    global.fetch = fetchMock;
    window.__BAKLOG_REPORT_ENDPOINT = "https://test.example/api/report";
  });

  afterEach(() => {
    delete global.fetch;
    delete window.__BAKLOG_REPORT_ENDPOINT;
    teardownWindow();
  });

  it("does not call fetch until explicitly invoked", () => {
    reportError(new Error("idle"));
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("POSTs trimmed bundle with contact and note caps", async () => {
    for (let i = 0; i < 30; i += 1) {
      reportError(new Error(`persisted-${i}`));
    }
    await submitBugReport({
      contact: `${"a".repeat(400)}@example.com`,
      note: "b".repeat(3000),
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, opts] = fetchMock.mock.calls[0];
    expect(url).toBe("https://test.example/api/report");
    expect(opts.method).toBe("POST");
    expect(opts.headers["Content-Type"]).toBe("application/json");
    const body = JSON.parse(opts.body);
    expect(body.bundle.bundle).toBe("baklog-bug-bundle");
    expect(body.bundle.errors.persisted.length).toBeLessThanOrEqual(25);
    expect(body.contact.length).toBe(320);
    expect(body.note.length).toBe(2000);
  });

  it("throws when the server returns a non-OK status", async () => {
    fetchMock.mockResolvedValueOnce({ ok: false, status: 502, json: async () => ({}) });
    await expect(submitBugReport()).rejects.toThrow("report failed: 502");
  });

  it("defaults endpoint to baklog.app when no override is set", () => {
    delete window.__BAKLOG_REPORT_ENDPOINT;
    expect(getBugReportEndpoint()).toBe("https://baklog.app/api/report");
    expect(BUG_REPORT_ENDPOINT).toBe("https://baklog.app/api/report");
  });
});
