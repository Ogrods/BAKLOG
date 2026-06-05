// Vercel serverless function: emails each waitlist signup to the founder via Resend.
// No database. Requires env vars: RESEND_API_KEY, NOTIFY_TO, NOTIFY_FROM.

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

function sanitizeEmail(raw) {
  if (typeof raw !== "string") return "";
  return raw.replace(/[\x00-\x1f\x7f]/g, "").trim();
}
const RATE_WINDOW_MS = 60_000;
const RATE_MAX = 5;

/** @type {Map<string, { start: number, count: number }>} */
const rateBuckets = new Map();

function clientIp(request) {
  const forwarded = request.headers.get("x-forwarded-for");
  if (forwarded) return forwarded.split(",")[0].trim();
  return request.headers.get("x-real-ip") || "unknown";
}

function isRateLimited(ip) {
  const now = Date.now();
  let entry = rateBuckets.get(ip);
  if (!entry || now - entry.start > RATE_WINDOW_MS) {
    entry = { start: now, count: 0 };
    rateBuckets.set(ip, entry);
  }
  entry.count += 1;
  if (rateBuckets.size > 10_000) {
    for (const [key, bucket] of rateBuckets) {
      if (now - bucket.start > RATE_WINDOW_MS) rateBuckets.delete(key);
    }
  }
  return entry.count > RATE_MAX;
}

export default {
  async fetch(request) {
    if (request.method !== "POST") {
      return Response.json({ error: "Method not allowed" }, { status: 405 });
    }

    if (isRateLimited(clientIp(request))) {
      return Response.json({ error: "Too many requests" }, {
        status: 429,
        headers: { "Retry-After": "60" },
      });
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

    try {
      const r = await fetch("https://api.resend.com/emails", {
        method: "POST",
        headers: {
          Authorization: `Bearer ${apiKey}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          from,
          to,
          reply_to: email,
          subject: "New BAKLOG waitlist signup",
          text: `New signup: ${email}\nTime: ${new Date().toISOString()}`,
        }),
      });

      if (!r.ok) {
        const detail = await r.text().catch(() => "");
        console.error("subscribe: Resend error", r.status, detail);
        return Response.json({ error: "Send failed" }, { status: 502 });
      }

      return Response.json({ ok: true });
    } catch (err) {
      console.error("subscribe: unexpected error", err);
      return Response.json({ error: "Send failed" }, { status: 502 });
    }
  },
};
