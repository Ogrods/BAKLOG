// Founder notification email via Resend (shared by Vercel functions).
// Env: RESEND_API_KEY, NOTIFY_FROM, NOTIFY_TO - same trio as /api/subscribe.

export function notifyConfig() {
  const apiKey = process.env.RESEND_API_KEY;
  const from = process.env.NOTIFY_FROM;
  const to = process.env.NOTIFY_TO;
  if (!apiKey || !from || !to) return null;
  return { apiKey, from, to };
}

export async function sendEmail(apiKey, payload) {
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

/** Email the founder; returns false (never throws) when unconfigured or Resend fails. */
export async function notifyFounder({ subject, text, replyTo }) {
  const cfg = notifyConfig();
  if (!cfg) {
    console.error("notify: missing RESEND_API_KEY / NOTIFY_FROM / NOTIFY_TO");
    return false;
  }
  try {
    await sendEmail(cfg.apiKey, {
      from: cfg.from,
      to: cfg.to,
      ...(replyTo ? { reply_to: replyTo } : {}),
      subject,
      text,
    });
    return true;
  } catch (err) {
    console.error("notify: founder email failed", err);
    return false;
  }
}
