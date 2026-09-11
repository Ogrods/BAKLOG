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

async function sendEmail(apiKey, payload) {
  const r = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  if (!r.ok) {
    const detail = await r.text().catch(() => "");
    throw new Error(`Resend ${r.status}: ${detail}`);
  }
  return r;
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

    const apiKey = process.env.RESEND_API_KEY;
    const from = process.env.NOTIFY_FROM;
    const to = process.env.NOTIFY_TO;
    if (!apiKey || !from || !to) {
      console.error("auth-signup-notify: missing RESEND_API_KEY / NOTIFY_FROM / NOTIFY_TO");
      return Response.json({ error: "Server not configured" }, { status: 500 });
    }

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
        ].join("\n"),
      });
    } catch (err) {
      console.error("auth-signup-notify: founder notification failed", err);
      return Response.json({ error: "Notification failed" }, { status: 502 });
    }

    return Response.json({ ok: true });
  },
};
