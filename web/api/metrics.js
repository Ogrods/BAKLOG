// Vercel serverless function: accepts opt-in anonymous aggregate metrics from
// the local app. No IP is stored — rate limiting uses IP transiently only.
// Optional: SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY (aggregate_metrics log).

import { checkRateLimit } from "./_rate-limit.js";

const MAX_BODY_BYTES = 16 * 1024;
const MAX_EVENTS = 50;
const MAX_SESSION_ID = 64;
const VALID_TYPES = new Set(["session_start", "impression", "click"]);

function clientIp(request) {
  const forwarded = request.headers.get("x-forwarded-for");
  if (forwarded) return forwarded.split(",")[0].trim();
  return request.headers.get("x-real-ip") || "unknown";
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

function sanitizeToken(raw, maxLen) {
  if (typeof raw !== "string") return "";
  return raw.replace(/[^\w-]/g, "").slice(0, maxLen);
}

function isValidPayload(body) {
  if (!body || typeof body !== "object") return false;
  if (body.bundle !== "baklog-metrics") return false;
  if (typeof body.app_version !== "string") return false;
  if (typeof body.session_id !== "string" || !body.session_id.trim()) return false;
  if (!Array.isArray(body.events) || body.events.length === 0) return false;
  return true;
}

function normalizeEvents(events) {
  const out = [];
  for (const ev of events.slice(0, MAX_EVENTS)) {
    if (!ev || typeof ev !== "object") continue;
    const type = String(ev.type || "").trim();
    if (!VALID_TYPES.has(type)) continue;
    const n = Number(ev.n);
    if (!Number.isFinite(n) || n < 1 || n > 10_000) continue;
    const placement = typeof ev.placement === "string" ? ev.placement.slice(0, 32) : null;
    const sponsor_id = typeof ev.sponsor_id === "string" ? ev.sponsor_id.slice(0, 64) : null;
    out.push({
      type,
      placement,
      sponsor_id,
      n: Math.floor(n),
    });
  }
  return out;
}

async function logToSupabase({ app_version, session_id, events, time }) {
  const url = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!url || !key) return;

  const r = await fetch(`${url}/rest/v1/aggregate_metrics`, {
    method: "POST",
    headers: {
      apikey: key,
      Authorization: `Bearer ${key}`,
      "Content-Type": "application/json",
      Prefer: "return=minimal",
    },
    body: JSON.stringify({
      app_version: String(app_version || "unknown").slice(0, 32),
      session_id,
      events,
      created_at: time,
    }),
  });
  if (!r.ok) {
    const detail = await r.text().catch(() => "");
    throw new Error(`Supabase ${r.status}: ${detail}`);
  }
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
    if (!isAllowedOrigin(origin)) {
      return jsonResponse({ error: "Origin not allowed" }, 403, request);
    }

    const ip = clientIp(request);
    const rate = await checkRateLimit(ip, { namespace: "metrics" });
    if (rate.misconfigured) {
      console.error("metrics: missing KV rate-limit credentials in production");
      return jsonResponse({ error: "Server not configured" }, 503, request);
    }
    if (rate.limited) {
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

    if (!isValidPayload(body)) {
      return jsonResponse({ error: "Invalid metrics payload" }, 400, request);
    }

    const session_id = sanitizeToken(body.session_id, MAX_SESSION_ID);
    if (!session_id) {
      return jsonResponse({ error: "Invalid session_id" }, 400, request);
    }

    const events = normalizeEvents(body.events);
    if (!events.length) {
      return jsonResponse({ error: "No valid events" }, 400, request);
    }

    const reportTime = new Date().toISOString();
    const app_version = String(body.app_version || "unknown").slice(0, 32);
    const summary = events.map(e => `${e.type}:${e.n}`).join(",");
    console.log(`metrics\t${reportTime}\t${app_version}\t${session_id}\t${summary}`);

    try {
      await logToSupabase({ app_version, session_id, events, time: reportTime });
    } catch (err) {
      console.error("metrics: supabase log failed", err);
    }

    return jsonResponse({ ok: true }, 200, request);
  },
};
