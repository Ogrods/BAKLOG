// Vercel serverless function: accepts opt-in bug reports from the local app,
// logs to Supabase (optional), emails the founder via Resend.
// Requires env vars: RESEND_API_KEY, NOTIFY_TO, NOTIFY_FROM.
// Optional: SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY (durable bug_reports log).

const RATE_WINDOW_MS = 60_000;
const RATE_MAX = 5;
const MAX_BODY_BYTES = 256 * 1024;
const MAX_CONTACT_LEN = 320;
const MAX_NOTE_LEN = 2000;

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

function isAllowedOrigin(origin) {
  if (!origin || typeof origin !== "string") return false;
  if (origin === "https://baklog.app") return true;
  try {
    const u = new URL(origin);
    if (u.protocol !== "http:") return false;
    if (u.hostname !== "127.0.0.1" && u.hostname !== "localhost") return false;
    return true;
  } catch {
    return false;
  }
}

function corsHeaders(request) {
  const origin = request.headers.get("Origin") || "";
  const headers = {
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
  };
  if (isAllowedOrigin(origin)) {
    headers["Access-Control-Allow-Origin"] = origin;
    headers.Vary = "Origin";
  }
  return headers;
}

function jsonResponse(body, status, request, extraHeaders = {}) {
  return Response.json(body, {
    status,
    headers: { ...corsHeaders(request), ...extraHeaders },
  });
}

function sanitizeText(raw, maxLen) {
  if (typeof raw !== "string") return "";
  return raw.replace(/[\x00-\x1f\x7f]/g, "").trim().slice(0, maxLen);
}

function isValidBundle(bundle) {
  return bundle
    && typeof bundle === "object"
    && bundle.bundle === "baklog-bug-bundle"
    && typeof bundle.app_version === "string"
    && bundle.errors
    && Array.isArray(bundle.errors.session)
    && Array.isArray(bundle.errors.persisted);
}

function topErrorSummary(bundle) {
  const session = bundle.errors?.session || [];
  const persisted = bundle.errors?.persisted || [];
  const latest = session[session.length - 1] || persisted[persisted.length - 1];
  if (!latest) return { message: "(no errors captured)", stack: "" };
  return {
    message: String(latest.message || "(no message)").slice(0, 500),
    stack: String(latest.stack || "").slice(0, 2000),
    name: String(latest.name || "Error"),
  };
}

async function logToSupabase({ bundle, contact, note, ip, time }) {
  const url = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!url || !key) return;

  const errorCount = (bundle.errors?.session_count ?? bundle.errors?.session?.length ?? 0)
    + (bundle.errors?.persisted_count ?? bundle.errors?.persisted?.length ?? 0);

  const r = await fetch(`${url}/rest/v1/bug_reports`, {
    method: "POST",
    headers: {
      apikey: key,
      Authorization: `Bearer ${key}`,
      "Content-Type": "application/json",
      Prefer: "return=minimal",
    },
    body: JSON.stringify({
      app_version: bundle.app_version || "unknown",
      ua: String(bundle.ua || "").slice(0, 256),
      view: bundle.runtime?.view || null,
      contact: contact || null,
      note: note || null,
      error_count: errorCount,
      bundle,
      ip,
      created_at: time,
    }),
  });
  if (!r.ok) {
    const detail = await r.text().catch(() => "");
    throw new Error(`Supabase ${r.status}: ${detail}`);
  }
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

export default {
  async fetch(request) {
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders(request) });
    }

    if (request.method !== "POST") {
      return jsonResponse({ error: "Method not allowed" }, 405, request);
    }

    const origin = request.headers.get("Origin") || "";
    if (origin && !isAllowedOrigin(origin)) {
      return jsonResponse({ error: "Origin not allowed" }, 403, request);
    }

    const ip = clientIp(request);
    if (isRateLimited(ip)) {
      return jsonResponse({ error: "Too many requests" }, 429, request, { "Retry-After": "60" });
    }

    const contentLength = Number(request.headers.get("content-length") || 0);
    if (contentLength > MAX_BODY_BYTES) {
      return jsonResponse({ error: "Payload too large" }, 413, request);
    }

    let rawText;
    try {
      rawText = await request.text();
    } catch {
      return jsonResponse({ error: "Invalid body" }, 400, request);
    }

    if (rawText.length > MAX_BODY_BYTES) {
      return jsonResponse({ error: "Payload too large" }, 413, request);
    }

    let body;
    try {
      body = JSON.parse(rawText);
    } catch {
      return jsonResponse({ error: "Invalid JSON" }, 400, request);
    }

    const website = typeof body.website === "string" ? body.website.trim() : "";
    if (website) return jsonResponse({ ok: true }, 200, request);

    const bundle = body.bundle;
    if (!isValidBundle(bundle)) {
      return jsonResponse({ error: "Invalid bug bundle" }, 400, request);
    }

    const contact = sanitizeText(body.contact, MAX_CONTACT_LEN);
    const note = sanitizeText(body.note, MAX_NOTE_LEN);

    const apiKey = process.env.RESEND_API_KEY;
    const from = process.env.NOTIFY_FROM;
    const to = process.env.NOTIFY_TO;
    if (!apiKey || !from || !to) {
      console.error("report: missing RESEND_API_KEY / NOTIFY_FROM / NOTIFY_TO");
      return jsonResponse({ error: "Server not configured" }, 500, request);
    }

    const reportTime = new Date().toISOString();
    const top = topErrorSummary(bundle);
    const view = bundle.runtime?.view || "unknown";
    const appVersion = bundle.app_version || "unknown";

    console.log(`bug_report\t${reportTime}\t${appVersion}\t${view}\t${contact || "(no contact)"}`);

    try {
      await logToSupabase({ bundle, contact, note, ip, time: reportTime });
    } catch (err) {
      console.error("report: supabase log failed", err);
    }

    const subject = `BAKLOG bug report: ${top.name} (${appVersion})`;
    const textSummary = [
      `App version: ${appVersion}`,
      `View: ${view}`,
      `Contact: ${contact || "(none)"}`,
      note ? `Note: ${note}` : null,
      "",
      `Latest error: ${top.name}: ${top.message}`,
      top.stack ? `\nStack:\n${top.stack}` : null,
      "",
      "Full bundle attached below.",
      "",
      JSON.stringify(bundle, null, 2),
    ].filter(Boolean).join("\n");

    try {
      await sendEmail(apiKey, {
        from,
        to,
        reply_to: contact || undefined,
        subject,
        text: textSummary,
      });
    } catch (err) {
      console.error("report: founder notification failed", err);
      return jsonResponse({ error: "Send failed" }, 502, request);
    }

    return jsonResponse({ ok: true }, 200, request);
  },
};
