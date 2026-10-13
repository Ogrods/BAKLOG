/* @vitest-environment node */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import authSignupNotifyHandler from "../web/api/auth-signup-notify.js";

const { fetch: handleAuthSignupNotify } = authSignupNotifyHandler;

const ENV_KEYS = [
  "AUTH_SIGNUP_WEBHOOK_SECRET",
  "RESEND_API_KEY",
  "NOTIFY_FROM",
  "NOTIFY_TO",
  "SUPABASE_URL",
  "SUPABASE_SERVICE_ROLE_KEY",
];

const WEBHOOK_SECRET = "signup_webhook_test_secret";

function makeRequest(body, { secret = WEBHOOK_SECRET, method = "POST" } = {}) {
  return new Request("https://baklog.app/api/auth-signup-notify", {
    method,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${secret}`,
    },
    body: JSON.stringify(body),
  });
}

const INSERT_PAYLOAD = {
  type: "INSERT",
  schema: "auth",
  table: "users",
  record: {
    id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    email: "newplayer@example.com",
    created_at: "2026-06-25T12:00:00.000Z",
    email_confirmed_at: null,
  },
};

const CONFIRMED_PAYLOAD = {
  ...INSERT_PAYLOAD,
  record: { ...INSERT_PAYLOAD.record, email_confirmed_at: "2026-06-25T12:01:00.000Z" },
};

describe("web/api/auth-signup-notify.js", () => {
  /** @type {import('vitest').Mock} */
  let fetchMock;

  beforeEach(() => {
    process.env.AUTH_SIGNUP_WEBHOOK_SECRET = WEBHOOK_SECRET;
    process.env.RESEND_API_KEY = "re_test_key";
    process.env.NOTIFY_FROM = "BAKLOG <accounts@baklog.app>";
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

  it("rejects missing webhook secret with 401", async () => {
    const res = await handleAuthSignupNotify(makeRequest(INSERT_PAYLOAD, { secret: "wrong" }));
    expect(res.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("ignores non-insert auth.users events", async () => {
    const res = await handleAuthSignupNotify(makeRequest({
      type: "UPDATE",
      schema: "auth",
      table: "users",
      record: INSERT_PAYLOAD.record,
    }));
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ ok: true, ignored: true });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("sends founder notification for auth.users INSERT", async () => {
    const res = await handleAuthSignupNotify(makeRequest(INSERT_PAYLOAD));
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("https://api.resend.com/emails");
    const payload = JSON.parse(init.body);
    expect(payload.to).toBe("founder@example.com");
    expect(payload.reply_to).toBe("newplayer@example.com");
    expect(payload.subject).toBe("New BAKLOG account: newplayer@example.com");
    expect(payload.text).toContain("newplayer@example.com");
    expect(payload.text).toContain("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee");
  });

  describe("pending Polar purchase", () => {
    const USER_ID = INSERT_PAYLOAD.record.id;

    function supabaseFetch({ pending, failLookup = false }) {
      return vi.fn(async (url, init = {}) => {
        const u = String(url);
        const method = (init.method || "GET").toUpperCase();
        if (u.includes("/rest/v1/polar_pending_entitlements")) {
          if (method === "GET") {
            if (failLookup) return { ok: false, status: 500, text: async () => "down" };
            return { ok: true, json: async () => (pending ? [pending] : []) };
          }
          return { ok: true, text: async () => "" };
        }
        if (u.includes(`/auth/v1/admin/users/${USER_ID}`)) {
          if (method === "GET") return { ok: true, json: async () => ({ app_metadata: { provider: "email" } }) };
          return { ok: true, json: async () => ({}) };
        }
        if (u === "https://api.resend.com/emails") return { ok: true, text: async () => "" };
        throw new Error(`unexpected fetch ${u} ${method}`);
      });
    }

    beforeEach(() => {
      process.env.SUPABASE_URL = "https://demo.supabase.co";
      process.env.SUPABASE_SERVICE_ROLE_KEY = "service-key";
    });

    const resendPayload = () =>
      JSON.parse(fetchMock.mock.calls.find(([u]) => u === "https://api.resend.com/emails")[1].body);
    const callsMatching = (fragment, method) =>
      fetchMock.mock.calls.filter(
        ([u, init]) => String(u).includes(fragment) && (init?.method || "GET").toUpperCase() === method,
      );

    it("applies a pending pro purchase and notes it in the founder email", async () => {
      fetchMock = supabaseFetch({
        pending: { email: "newplayer@example.com", plan: "pro", applied_at: null, last_event_type: "order.paid" },
      });
      global.fetch = fetchMock;
      const res = await handleAuthSignupNotify(makeRequest(CONFIRMED_PAYLOAD));
      expect(res.status).toBe(200);
      const put = callsMatching("/auth/v1/admin/users/", "PUT");
      expect(put).toHaveLength(1);
      expect(JSON.parse(put[0][1].body).app_metadata).toMatchObject({ provider: "email", plan: "pro", paid: true });
      const patch = callsMatching("/rest/v1/polar_pending_entitlements", "PATCH");
      expect(patch).toHaveLength(1);
      expect(JSON.parse(patch[0][1].body).applied_user_id).toBe(USER_ID);
      expect(resendPayload().text).toContain("Pro applied from pending Polar purchase (order.paid)");
    });

    it("defers a pending purchase until the email is confirmed", async () => {
      fetchMock = supabaseFetch({
        pending: { email: "newplayer@example.com", plan: "pro", applied_at: null, last_event_type: "order.paid" },
      });
      global.fetch = fetchMock;
      const res = await handleAuthSignupNotify(makeRequest(INSERT_PAYLOAD));
      expect(res.status).toBe(200);
      expect(callsMatching("/auth/v1/admin/users/", "PUT")).toHaveLength(0);
      expect(callsMatching("/rest/v1/polar_pending_entitlements", "PATCH")).toHaveLength(0);
      expect(resendPayload().text).toContain("applies once this email is confirmed");
    });

    it("leaves the account alone when there is no pending row", async () => {
      fetchMock = supabaseFetch({ pending: null });
      global.fetch = fetchMock;
      const res = await handleAuthSignupNotify(makeRequest(INSERT_PAYLOAD));
      expect(res.status).toBe(200);
      expect(callsMatching("/auth/v1/admin/users/", "PUT")).toHaveLength(0);
      expect(resendPayload().text).not.toContain("Polar");
    });

    it("skips already-applied or free pending rows", async () => {
      for (const pending of [
        { email: "newplayer@example.com", plan: "pro", applied_at: "2026-10-01T00:00:00Z" },
        { email: "newplayer@example.com", plan: "free", applied_at: null },
      ]) {
        fetchMock = supabaseFetch({ pending });
        global.fetch = fetchMock;
        await handleAuthSignupNotify(makeRequest(INSERT_PAYLOAD));
        expect(callsMatching("/auth/v1/admin/users/", "PUT")).toHaveLength(0);
      }
    });

    it("still notifies (flagging the failure) when the lookup fails", async () => {
      fetchMock = supabaseFetch({ pending: null, failLookup: true });
      global.fetch = fetchMock;
      const res = await handleAuthSignupNotify(makeRequest(INSERT_PAYLOAD));
      expect(res.status).toBe(200);
      expect(resendPayload().text).toContain("FAILED");
    });
  });

  it("rejects an oversized declared Content-Length before reading the body", async () => {
    const text = vi.fn(async () => "{}");
    const res = await handleAuthSignupNotify({
      method: "POST",
      headers: new Headers({ authorization: `Bearer ${WEBHOOK_SECRET}`, "content-length": String(64 * 1024) }),
      text,
    });
    expect(res.status).toBe(413);
    expect(text).not.toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects an oversized body even without a Content-Length header", async () => {
    const big = { ...INSERT_PAYLOAD, padding: "x".repeat(40 * 1024) };
    const req = makeRequest(big);
    expect(req.headers.get("content-length")).toBeNull();
    const res = await handleAuthSignupNotify(req);
    expect(res.status).toBe(413);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("returns 400 on invalid JSON", async () => {
    const res = await handleAuthSignupNotify(new Request("https://baklog.app/api/auth-signup-notify", {
      method: "POST",
      headers: { Authorization: `Bearer ${WEBHOOK_SECRET}` },
      body: "{not json",
    }));
    expect(res.status).toBe(400);
  });

  it("returns 502 when Resend fails", async () => {
    fetchMock.mockResolvedValueOnce({ ok: false, text: async () => "boom" });
    const res = await handleAuthSignupNotify(makeRequest(INSERT_PAYLOAD));
    expect(res.status).toBe(502);
    expect(await res.json()).toEqual({ error: "Notification failed" });
  });
});
