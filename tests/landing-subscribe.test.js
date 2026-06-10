/* @vitest-environment node */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import subscribeHandler from "../landing/api/subscribe.js";

const { fetch: handleSubscribe } = subscribeHandler;

const ENV_KEYS = [
  "RESEND_API_KEY",
  "NOTIFY_FROM",
  "NOTIFY_TO",
  "SUPABASE_URL",
  "SUPABASE_SERVICE_ROLE_KEY",
  "KV_REST_API_URL",
  "KV_REST_API_TOKEN",
  "UPSTASH_REDIS_REST_URL",
  "UPSTASH_REDIS_REST_TOKEN",
  "VERCEL_ENV",
];

function makeRequest(body, { ip = "10.0.0.1", method = "POST", contentLength } = {}) {
  const headers = new Headers({
    "Content-Type": "application/json",
    "x-forwarded-for": ip,
  });
  if (contentLength != null) headers.set("content-length", String(contentLength));
  return {
    method,
    headers,
    json: async () => body,
  };
}

describe("landing/api/subscribe.js", () => {
  /** @type {import('vitest').Mock} */
  let fetchMock;

  beforeEach(() => {
    process.env.RESEND_API_KEY = "re_test_key";
    process.env.NOTIFY_FROM = "BAKLOG <waitlist@baklog.app>";
    process.env.NOTIFY_TO = "founder@example.com";
    delete process.env.SUPABASE_URL;
    delete process.env.SUPABASE_SERVICE_ROLE_KEY;
    delete process.env.KV_REST_API_URL;
    delete process.env.KV_REST_API_TOKEN;
    delete process.env.UPSTASH_REDIS_REST_URL;
    delete process.env.UPSTASH_REDIS_REST_TOKEN;
    delete process.env.VERCEL_ENV;
    fetchMock = vi.fn(async () => ({ ok: true, text: async () => "" }));
    global.fetch = fetchMock;
  });

  afterEach(() => {
    delete global.fetch;
    for (const key of ENV_KEYS) delete process.env[key];
  });

  it("returns ok for honeypot submissions without sending email", async () => {
    const res = await handleSubscribe(makeRequest({
      email: "bot@example.com",
      website: "https://spam.example",
    }));
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ ok: true });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects oversized Content-Length with 413", async () => {
    const res = await handleSubscribe(makeRequest(
      { email: "tester@example.com" },
      { ip: "10.0.0.61", contentLength: 9000 },
    ));
    expect(res.status).toBe(413);
    expect(await res.json()).toEqual({ error: "Payload too large" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects invalid email with 400", async () => {
    const res = await handleSubscribe(makeRequest({ email: "not-an-email" }));
    expect(res.status).toBe(400);
    expect(await res.json()).toEqual({ error: "Invalid email" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("accepts email after stripping control characters", async () => {
    const res = await handleSubscribe(makeRequest({
      email: "tester\x00@example.com",
    }, { ip: "10.0.0.77" }));
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const [, founderOpts] = fetchMock.mock.calls[0];
    const founderPayload = JSON.parse(founderOpts.body);
    expect(founderPayload.subject).toContain("tester@example.com");
  });

  it("rate limits more than five requests per IP per minute", async () => {
    const ip = "192.168.1.55";
    for (let i = 0; i < 5; i += 1) {
      const res = await handleSubscribe(makeRequest({
        email: `user${i}@example.com`,
      }, { ip }));
      expect(res.status).toBe(200);
    }
    const blocked = await handleSubscribe(makeRequest({
      email: "blocked@example.com",
    }, { ip }));
    expect(blocked.status).toBe(429);
    expect(await blocked.json()).toEqual({ error: "Too many requests" });
  });

  it("returns 503 in production when KV credentials are missing", async () => {
    process.env.VERCEL_ENV = "production";
    const res = await handleSubscribe(makeRequest({ email: "prod@example.com" }));
    expect(res.status).toBe(503);
    expect(await res.json()).toEqual({ error: "Server not configured" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("returns 500 when Resend env vars are missing", async () => {
    delete process.env.RESEND_API_KEY;
    const res = await handleSubscribe(makeRequest({ email: "tester@example.com" }));
    expect(res.status).toBe(500);
    expect(await res.json()).toEqual({ error: "Server not configured" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("returns 502 when founder notification fails", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 500,
      text: async () => "upstream error",
    });
    const res = await handleSubscribe(makeRequest({ email: "tester@example.com" }));
    expect(res.status).toBe(502);
    expect(await res.json()).toEqual({ error: "Send failed" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("still returns ok when confirmation auto-reply fails", async () => {
    fetchMock
      .mockResolvedValueOnce({ ok: true, text: async () => "" })
      .mockResolvedValueOnce({
        ok: false,
        status: 500,
        text: async () => "welcome failed",
      });
    const res = await handleSubscribe(makeRequest({ email: "tester@example.com" }));
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("sends founder notification and confirmation for a valid signup", async () => {
    const res = await handleSubscribe(makeRequest(
      { email: "tester@example.com" },
      { ip: "10.0.0.88" },
    ));
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledTimes(2);

    const [, founderOpts] = fetchMock.mock.calls[0];
    const founderPayload = JSON.parse(founderOpts.body);
    expect(founderPayload.to).toBe("founder@example.com");
    expect(founderPayload.reply_to).toBe("tester@example.com");

    const [, welcomeOpts] = fetchMock.mock.calls[1];
    const welcomePayload = JSON.parse(welcomeOpts.body);
    expect(welcomePayload.to).toBe("tester@example.com");
    expect(welcomePayload.subject).toContain("invite list");
  });
});
