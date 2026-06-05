// Vercel serverless function: emails each waitlist signup to the founder via Resend.
// No database. Requires env vars: RESEND_API_KEY, NOTIFY_TO, NOTIFY_FROM.
//   RESEND_API_KEY  - from https://resend.com (API Keys)
//   NOTIFY_FROM     - verified sender, e.g. "BAKLOG <waitlist@baklog.app>"
//   NOTIFY_TO        - where signups land, e.g. "you@baklog.app"

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

export async function POST(request) {
  let body;
  try {
    body = await request.json();
  } catch {
    body = {};
  }

  const email = typeof body.email === "string" ? body.email.trim() : "";
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
}
