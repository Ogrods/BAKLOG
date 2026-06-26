/* @vitest-environment node */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import authSignupNotifyHandler from "../landing/api/auth-signup-notify.js";

const { fetch: handleAuthSignupNotify } = authSignupNotifyHandler;

const ENV_KEYS = [
  "AUTH_SIGNUP_WEBHOOK_SECRET",
  "RESEND_API_KEY",
  "NOTIFY_FROM",
  "NOTIFY_TO",
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

describe("landing/api/auth-signup-notify.js", () => {
  /** @type {import('vitest').Mock} */
  let fetchMock;

  beforeEach(() => {
    process.env.AUTH_SIGNUP_WEBHOOK_SECRET = WEBHOOK_SECRET;
    process.env.RESEND_API_KEY = "re_test_key";
    process.env.NOTIFY_FROM = "BAKLOG <accounts@baklog.app>";
    process.env.NOTIFY_TO = "founder@example.com";
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

  it("returns 502 when Resend fails", async () => {
    fetchMock.mockResolvedValueOnce({ ok: false, text: async () => "boom" });
    const res = await handleAuthSignupNotify(makeRequest(INSERT_PAYLOAD));
    expect(res.status).toBe(502);
    expect(await res.json()).toEqual({ error: "Notification failed" });
  });
});
