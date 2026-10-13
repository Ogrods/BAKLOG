// Vercel serverless function: receives Supabase Database Webhooks on auth.users
// INSERT and emails the founder via Resend when someone creates a BAKLOG account.
//
// Required env vars:
//   AUTH_SIGNUP_WEBHOOK_SECRET  - shared secret; set the same value on the Supabase webhook
//   RESEND_API_KEY, NOTIFY_FROM, NOTIFY_TO  - same trio as /api/subscribe
//
// Supabase setup (once): Database → Webhooks → auth.users → Insert → POST
// https://baklog.app/api/auth-signup-notify with header
// Authorization: Bearer <AUTH_SIGNUP_WEBHOOK_SECRET>
//
// Optional SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY: when set, a pending Polar
// purchase for the new email (polar_pending_entitlements, written by
// polar-webhook.js) is applied to the account as app_metadata.plan, but only
// when the email is already confirmed; otherwise comp-expire.js applies it after
// confirmation so an unverified signup cannot claim someone else's purchase.

import { notifyConfig, sendEmail } from "./_notify.js";
import { findPendingEntitlement, markPendingApplied, setUserPlan } from "./_polar-pending.js";

const MAX_BODY_BYTES = 32 * 1024;

function constantTimeEqual(a, b) {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i += 1) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

function verifyWebhookSecret(request) {
  const expected = (process.env.AUTH_SIGNUP_WEBHOOK_SECRET || "").trim();
  if (!expected) return false;
  const header = request.headers.get("authorization") || "";
  const prefix = "Bearer ";
  if (!header.startsWith(prefix)) return false;
  const provided = header.slice(prefix.length).trim();
  return provided && constantTimeEqual(provided, expected);
}

/** Apply a pending Polar Pro purchase to the new account. Returns a founder-email line or "". */
async function applyPendingPurchase(signup) {
  const url = (process.env.SUPABASE_URL || "").trim().replace(/\/+$/, "");
  const key = (process.env.SUPABASE_SERVICE_ROLE_KEY || "").trim();
  if (!url || !key) return "";
  try {
    const pending = await findPendingEntitlement({ url, key, email: signup.email });
    if (!pending || pending.applied_at || pending.plan !== "pro") return "";
    if (!signup.confirmedAt) {
      return "Pending Polar purchase found. Pro applies once this email is confirmed (daily comp-expire cron).";
    }
    await setUserPlan({ url, key, userId: signup.id, plan: "pro" });
    await markPendingApplied({ url, key, email: signup.email, userId: signup.id });
    return `Pro applied from pending Polar purchase (${pending.last_event_type || "unknown event"}).`;
  } catch (err) {
    console.error("auth-signup-notify: applying pending Polar purchase failed", err);
    return "Pending Polar purchase lookup/apply FAILED - grant manually with scripts/grant_beta_pro.py.";
  }
}

function parseSignupPayload(body) {
  if (!body || typeof body !== "object") return null;
  if (body.type !== "INSERT") return null;
  if (body.schema !== "auth" || body.table !== "users") return null;
  const record = body.record;
  if (!record || typeof record !== "object") return null;
  const id = typeof record.id === "string" ? record.id.trim() : "";
  const email = typeof record.email === "string" ? record.email.trim() : "";
  if (!id || !email) return null;
  const createdAt = typeof record.created_at === "string" ? record.created_at : "";
  const confirmedAt = typeof record.email_confirmed_at === "string" ? record.email_confirmed_at : "";
  return { id, email, createdAt, confirmedAt };
}

export default {
  async fetch(request) {
    if (request.method !== "POST") {
      return Response.json({ error: "Method not allowed" }, { status: 405 });
    }

    if (!verifyWebhookSecret(request)) {
      return Response.json({ error: "Unauthorized" }, { status: 401 });
    }

    const contentLength = Number(request.headers.get("content-length") || 0);
    if (contentLength > MAX_BODY_BYTES) {
      return Response.json({ error: "Payload too large" }, { status: 413 });
    }

    let body;
    try {
      body = await request.json();
    } catch {
      return Response.json({ error: "Invalid JSON" }, { status: 400 });
    }

    const signup = parseSignupPayload(body);
    if (!signup) {
      return Response.json({ ok: true, ignored: true });
    }

    const proLine = await applyPendingPurchase(signup);

    const cfg = notifyConfig();
    if (!cfg) {
      console.error("auth-signup-notify: missing RESEND_API_KEY / NOTIFY_FROM / NOTIFY_TO");
      return Response.json({ error: "Server not configured" }, { status: 500 });
    }
    const { apiKey, from, to } = cfg;

    const time = signup.createdAt || new Date().toISOString();
    const confirmLine = signup.confirmedAt
      ? `Email confirmed: ${signup.confirmedAt}`
      : "Email confirmed: (pending verification)";

    try {
      await sendEmail(apiKey, {
        from,
        to,
        reply_to: signup.email,
        subject: `New BAKLOG account: ${signup.email}`,
        text: [
          "Someone created a BAKLOG account in Supabase.",
          "",
          `Email: ${signup.email}`,
          `User id: ${signup.id}`,
          `Created: ${time}`,
          confirmLine,
          ...(proLine ? ["", proLine] : []),
        ].join("\n"),
      });
    } catch (err) {
      console.error("auth-signup-notify: founder notification failed", err);
      return Response.json({ error: "Notification failed" }, { status: 502 });
    }

    return Response.json({ ok: true });
  },
};
