// Vercel serverless function: logs each waitlist signup (optional Supabase),
// emails the founder via Resend, then sends the signer a confirmation auto-reply.
// Requires env vars: RESEND_API_KEY, NOTIFY_TO, NOTIFY_FROM.
// Production also requires KV_REST_API_* or UPSTASH_REDIS_REST_* (distributed rate limit).
// Optional: WELCOME_FROM (defaults to NOTIFY_FROM), WELCOME_REPLY_TO (defaults to NOTIFY_TO),
// SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY (durable waitlist log).

import { checkRateLimit } from "./_rate-limit.js";

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const MAX_BODY_BYTES = 8 * 1024;

function sanitizeEmail(raw) {
  if (typeof raw !== "string") return "";
  return raw.replace(/[\x00-\x1f\x7f]/g, "").trim();
}

// Never write raw signup emails to the platform logs. A short SHA-256 prefix is
// enough to correlate duplicate submissions without storing PII in plaintext.
async function emailLogTag(email) {
  try {
    const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(email));
    const hex = Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, "0")).join("");
    return `sha256:${hex.slice(0, 8)}`;
  } catch {
    return "sha256:unknown";
  }
}
function clientIp(request) {
  const forwarded = request.headers.get("x-forwarded-for");
  if (forwarded) return forwarded.split(",")[0].trim();
  return request.headers.get("x-real-ip") || "unknown";
}

async function logToSupabase({ email, ip, time }) {
  const url = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!url || !key) return false;

  const r = await fetch(`${url}/rest/v1/waitlist`, {
    method: "POST",
    headers: {
      apikey: key,
      Authorization: `Bearer ${key}`,
      "Content-Type": "application/json",
      Prefer: "resolution=ignore-duplicates,return=minimal",
    },
    body: JSON.stringify({ email, ip, source: "landing", created_at: time }),
  });
  if (r.ok || r.status === 409) {
    // 409 = duplicate email on unique constraint; already on the list.
    return true;
  }
  const detail = await r.text().catch(() => "");
  throw new Error(`Supabase ${r.status}: ${detail}`);
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

const CONFIRM_SUBJECT = "You're on the BAKLOG invite list";

const CONFIRM_TEXT = `Thanks for requesting a BAKLOG invite.

You're on the list. BAKLOG is in invite-only beta and we're onboarding in small waves, so you'll get a follow-up here when your spot opens up.

A quick refresher on what you signed up for:
- One honest backlog across every store - 12 libraries and 8 wishlists, all on your machine.
- Local-first: credentials stay encrypted; nothing is uploaded by default.
- Claimable Now surfaces free giveaways; importing your library stays free forever.

No action needed right now - just keep an eye on your inbox.

- The BAKLOG team
https://baklog.app`;

const CONFIRM_HTML = `<!doctype html>
<html>
  <body style="margin:0;background:#0f172a;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#e2e8f0;">
    <div style="max-width:520px;margin:0 auto;padding:32px 24px;">
      <h1 style="font-size:20px;margin:0 0 16px;color:#f8fafc;">You're on the BAKLOG invite list</h1>
      <p style="font-size:15px;line-height:1.6;margin:0 0 16px;">Thanks for requesting a BAKLOG invite. BAKLOG is in invite-only beta and we're onboarding in small waves, so you'll get a follow-up here when your spot opens up.</p>
      <p style="font-size:15px;line-height:1.6;margin:0 0 8px;">A quick refresher on what you signed up for:</p>
      <ul style="font-size:15px;line-height:1.6;margin:0 0 16px;padding-left:20px;">
        <li>One honest backlog across every store - 12 libraries and 8 wishlists, all on your machine.</li>
        <li>Local-first: credentials stay encrypted; nothing is uploaded by default.</li>
        <li>Claimable Now surfaces free giveaways; importing your library stays free forever.</li>
      </ul>
      <p style="font-size:15px;line-height:1.6;margin:0 0 24px;">No action needed right now - just keep an eye on your inbox.</p>
      <p style="font-size:14px;line-height:1.6;margin:0;color:#94a3b8;">- The BAKLOG team<br /><a href="https://baklog.app" style="color:#38bdf8;">baklog.app</a></p>
    </div>
  </body>
</html>`;

export default {
  async fetch(request) {
    if (request.method !== "POST") {
      return Response.json({ error: "Method not allowed" }, { status: 405 });
    }

    const ip = clientIp(request);
    const rate = await checkRateLimit(ip, { namespace: "subscribe" });
    if (rate.misconfigured) {
      console.error("subscribe: missing KV rate-limit credentials in production");
      return Response.json({ error: "Server not configured" }, { status: 503 });
    }
    if (rate.limited) {
      return Response.json({ error: "Too many requests" }, {
        status: 429,
        headers: { "Retry-After": "60" },
      });
    }

    const contentLength = Number(request.headers.get("content-length") || 0);
    if (contentLength > MAX_BODY_BYTES) {
      return Response.json({ error: "Payload too large" }, { status: 413 });
    }

    let body;
    try {
      body = await request.json();
    } catch {
      body = {};
    }

    const email = sanitizeEmail(body.email);
    const website = typeof body.website === "string" ? body.website.trim() : "";

    // Honeypot: bots fill the hidden field. Pretend success, do nothing.
    if (website) return Response.json({ ok: true });

    if (!EMAIL_RE.test(email) || email.length > 320) {
      return Response.json({ error: "Invalid email" }, { status: 400 });
    }

    const apiKey = process.env.RESEND_API_KEY;
    const from = process.env.NOTIFY_FROM;
    const to = process.env.NOTIFY_TO;
    if (!apiKey || !from || !to) {
      console.error("subscribe: missing RESEND_API_KEY / NOTIFY_FROM / NOTIFY_TO");
      return Response.json({ error: "Server not configured" }, { status: 500 });
    }

    const signupTime = new Date().toISOString();
    console.log(`waitlist_signup\t${signupTime}\t${await emailLogTag(email)}`);
    // Without Supabase, the Vercel function log above is the durable capture path (see landing/README.md).

    try {
      await logToSupabase({ email, ip, time: signupTime });
    } catch (err) {
      console.error("subscribe: supabase log failed", err);
    }

    try {
      await sendEmail(apiKey, {
        from,
        to,
        reply_to: email,
        subject: `New BAKLOG invite request: ${email}`,
        text: `New signup: ${email}\nTime: ${signupTime}`,
      });
    } catch (err) {
      console.error("subscribe: founder notification failed", err);
    }

    // Confirmation auto-reply to the signer. Best-effort: a failure here must not
    // fail the request, since the signup was already captured above.
    try {
      await sendEmail(apiKey, {
        from: process.env.WELCOME_FROM || from,
        to: email,
        reply_to: process.env.WELCOME_REPLY_TO || to,
        subject: CONFIRM_SUBJECT,
        text: CONFIRM_TEXT,
        html: CONFIRM_HTML,
      });
    } catch (err) {
      console.error("subscribe: confirmation auto-reply failed", err);
    }

    return Response.json({ ok: true });
  },
};
