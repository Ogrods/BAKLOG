/* @vitest-environment node */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import reportHandler from "../landing/api/report.js";

const { fetch: handleReport } = reportHandler;

const ENV_KEYS = ["RESEND_API_KEY", "NOTIFY_FROM", "NOTIFY_TO", "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"];

function validBundle() {
  return {
    bundle: "baklog-bug-bundle",
    app_version: "0.6.0-test",
    ua: "vitest",
    runtime: { view: "library" },
    errors: {
      session: [{ message: "boom", name: "Error", stack: "" }],
      persisted: [],
    },
  };
}

function makeRequest(body, { ip = "10.0.0.1", method = "POST", contentLength, origin = "https://baklog.app" } = {}) {
  const text = typeof body === "string" ? body : JSON.stringify(body);
  const headers = new Headers({
    "Content-Type": "application/json",
    "x-forwarded-for": ip,
  });
  if (origin != null) headers.set("Origin", origin);
  if (contentLength != null) {
    headers.set("content-length", String(contentLength));
  }
  return {
    method,
    headers,
    text: async () => text,
  };
}

describe("landing/api/report.js", () => {
  /** @type {import('vitest').Mock} */
  let fetchMock;

  beforeEach(() => {
    process.env.RESEND_API_KEY = "re_test_key";
    process.env.NOTIFY_FROM = "BAKLOG <waitlist@baklog.app>";
    process.env.NOTIFY_TO = "founder@example.com";
    delete process.env.SUPABASE_URL;
    delete process.env.SUPABASE_SERVICE_ROLE_KEY;
    fetchMock = vi.fn(async () => ({ ok: true, text: async () => "" }));
    global.fetch = fetchMock;
  });

  afterEach(() => {
    delete global.fetch;
    for (const key of ENV_KEYS) delete process.env[key];
  });

  it("rejects requests with no Origin header", async () => {
    const res = await handleReport(makeRequest({ bundle: validBundle() }, { origin: null }));
    expect(res.status).toBe(403);
    expect(await res.json()).toEqual({ error: "Origin not allowed" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects requests from a foreign Origin", async () => {
    const res = await handleReport(makeRequest({ bundle: validBundle() }, { origin: "https://evil.example" }));
    expect(res.status).toBe(403);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("omits reply_to when contact is not a valid email", async () => {
    const res = await handleReport(makeRequest({
      bundle: validBundle(),
      contact: "not an email",
    }, { ip: "10.0.0.51" }));
    expect(res.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [, opts] = fetchMock.mock.calls[0];
    const payload = JSON.parse(opts.body);
    expect(payload.reply_to).toBeUndefined();
  });

  it("returns ok for honeypot submissions without sending email", async () => {
    const res = await handleReport(makeRequest({
      website: "https://spam.example",
      bundle: { bundle: "not-valid" },
    }));
    expect(res.status).toBe(200);
    const json = await res.json();
    expect(json.ok).toBe(true);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects invalid bug bundles with 400", async () => {
    const res = await handleReport(makeRequest({ bundle: { bundle: "wrong-shape" } }));
    expect(res.status).toBe(400);
    expect(await res.json()).toEqual({ error: "Invalid bug bundle" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects oversized Content-Length with 413", async () => {
    const res = await handleReport(makeRequest(
      { bundle: validBundle() },
      { contentLength: 300_000 },
    ));
    expect(res.status).toBe(413);
    expect(await res.json()).toEqual({ error: "Payload too large" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects oversized body text with 413", async () => {
    const huge = JSON.stringify({ bundle: validBundle(), pad: "x".repeat(260 * 1024) });
    const res = await handleReport(makeRequest(huge));
    expect(res.status).toBe(413);
    expect(await res.json()).toEqual({ error: "Payload too large" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rate limits more than five requests per IP per minute", async () => {
    const ip = "192.168.1.99";
    for (let i = 0; i < 5; i += 1) {
      const res = await handleReport(makeRequest({ bundle: validBundle() }, { ip }));
      expect(res.status).toBe(200);
    }
    const blocked = await handleReport(makeRequest({ bundle: validBundle() }, { ip }));
    expect(blocked.status).toBe(429);
    expect(await blocked.json()).toEqual({ error: "Too many requests" });
  });

  it("returns 502 when Resend send fails", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 500,
      text: async () => "upstream error",
    });
    const res = await handleReport(makeRequest({ bundle: validBundle() }));
    expect(res.status).toBe(502);
    expect(await res.json()).toEqual({ error: "Send failed" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url] = fetchMock.mock.calls[0];
    expect(url).toBe("https://api.resend.com/emails");
  });

  it("sends email for a valid bundle", async () => {
    const res = await handleReport(makeRequest({
      bundle: validBundle(),
      contact: "tester@example.com",
      note: "repro steps",
    }, { ip: "10.0.0.42" }));
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [, opts] = fetchMock.mock.calls[0];
    const payload = JSON.parse(opts.body);
    expect(payload.to).toBe("founder@example.com");
    expect(payload.reply_to).toBe("tester@example.com");
    expect(payload.subject).toContain("BAKLOG bug report");
  });

  it("uses ManualReport subject when the bundle has no captured errors", async () => {
    const res = await handleReport(makeRequest({
      bundle: {
        ...validBundle(),
        errors: { session: [], persisted: [] },
      },
      note: "Pro activation failed",
    }, { ip: "10.0.0.88" }));
    expect(res.status).toBe(200);
    const [, opts] = fetchMock.mock.calls[0];
    const payload = JSON.parse(opts.body);
    expect(payload.subject).toContain("ManualReport");
    expect(payload.text).toContain("ManualReport: (no errors captured)");
    expect(payload.text).not.toContain("undefined:");
  });
});
