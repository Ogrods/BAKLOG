// Vercel serverless function: emails each waitlist signup to the founder via Resend.
// No database. Requires env vars: RESEND_API_KEY, NOTIFY_TO, NOTIFY_FROM.
//   RESEND_API_KEY  - from https://resend.com (API Keys)
//   NOTIFY_FROM     - verified sender, e.g. "BAKLOG <waitlist@baklog.app>"
//   NOTIFY_TO        - where signups land, e.g. "you@baklog.app"

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

async function readJsonBody(req) {
  if (req.body && typeof req.body === "object") return req.body;
  if (typeof req.body === "string" && req.body.length) {
    try { return JSON.parse(req.body); } catch { return {}; }
  }
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  if (!chunks.length) return {};
  try { return JSON.parse(Buffer.concat(chunks).toString("utf8")); } catch { return {}; }
}

module.exports = async function handler(req, res) {
  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    return res.status(405).json({ error: "Method not allowed" });
  }

  const body = await readJsonBody(req);
  const email = typeof body.email === "string" ? body.email.trim() : "";
  const website = typeof body.website === "string" ? body.website.trim() : "";

  // Honeypot: bots fill the hidden field. Pretend success, do nothing.
  if (website) return res.status(200).json({ ok: true });

  if (!EMAIL_RE.test(email) || email.length > 320) {
    return res.status(400).json({ error: "Invalid email" });
  }

  const apiKey = process.env.RESEND_API_KEY;
  const from = process.env.NOTIFY_FROM;
  const to = process.env.NOTIFY_TO;
  if (!apiKey || !from || !to) {
    console.error("subscribe: missing RESEND_API_KEY / NOTIFY_FROM / NOTIFY_TO");
    return res.status(500).json({ error: "Server not configured" });
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
      return res.status(502).json({ error: "Send failed" });
    }

    return res.status(200).json({ ok: true });
  } catch (err) {
    console.error("subscribe: unexpected error", err);
    return res.status(502).json({ error: "Send failed" });
  }
}
