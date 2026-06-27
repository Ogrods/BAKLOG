// Vercel serverless: read-only Pro cloud mirror (Supabase Storage).
// GET /api/mirror — list artifacts for signed-in Pro user
// GET /api/mirror?path=games_steam.json — download one artifact
// Requires BAKLOG_SUPABASE_URL + BAKLOG_SUPABASE_ANON_KEY on Vercel.

import { checkRateLimit } from "./_rate-limit.js";

const MIRROR_BUCKET = "baklog-mirror";
const ALLOWED_ARTIFACT =
  /^(games_[a-z0-9_]+\.json|games_wishlist_[a-z0-9_]+\.json|itad_prices\.json|free_claims\.json|data\/personal\.json)$/;

function pickEnv(...keys) {
  for (const key of keys) {
    const val = process.env[key];
    if (typeof val === "string" && val.trim()) return val.trim();
  }
  return "";
}

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
    return u.port === "8765" || u.port === "8766" || u.port === "";
  } catch {
    return false;
  }
}

function corsHeaders(request) {
  const origin = request.headers.get("Origin") || "";
  const headers = {
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Authorization, Content-Type",
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

function extractPlan(user) {
  const meta = user?.app_metadata || {};
  const plan = String(meta.plan || user?.plan || "").trim().toLowerCase();
  return plan === "pro" || plan === "paid" || plan === "premium";
}

async function verifySession(request, supabaseUrl, anonKey) {
  const auth = request.headers.get("Authorization") || "";
  if (!auth.startsWith("Bearer ")) return null;
  const res = await fetch(`${supabaseUrl}/auth/v1/user`, {
    headers: { apikey: anonKey, Authorization: auth },
  });
  if (!res.ok) return null;
  const user = await res.json();
  if (!extractPlan(user)) return null;
  return { auth, user };
}

function storageBase(supabaseUrl) {
  return `${supabaseUrl.replace(/\/$/, "")}/storage/v1/object`;
}

export default {
  async fetch(request) {
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders(request) });
    }
    if (request.method !== "GET") {
      return jsonResponse({ error: "Method not allowed" }, 405, request);
    }

    const ip = clientIp(request);
    const rate = await checkRateLimit(ip, { namespace: "mirror" });
    if (rate.misconfigured) {
      return jsonResponse({ error: "Server not configured" }, 503, request);
    }
    if (rate.limited) {
      return jsonResponse({ error: "Too many requests" }, 429, request, { "Retry-After": "60" });
    }

    const supabaseUrl = pickEnv("BAKLOG_SUPABASE_URL", "SUPABASE_URL");
    const anonKey = pickEnv("BAKLOG_SUPABASE_ANON_KEY", "SUPABASE_ANON_KEY");
    if (!supabaseUrl || !anonKey) {
      return jsonResponse({ error: "Mirror not configured" }, 503, request);
    }

    const session = await verifySession(request, supabaseUrl, anonKey);
    if (!session) {
      return jsonResponse({ error: "Pro sign-in required" }, 403, request);
    }

    const userId = String(session.user.id || "").trim();
    const url = new URL(request.url);
    const profileId = (url.searchParams.get("profile") || userId).trim();
    const artifact = (url.searchParams.get("path") || "").trim();
    const prefix = `${userId}/${profileId}`;

    if (artifact) {
      if (!ALLOWED_ARTIFACT.test(artifact)) {
        return jsonResponse({ error: "Invalid artifact path" }, 400, request);
      }
      const objectKey = `${prefix}/${artifact}`.split("/").map(encodeURIComponent).join("/");
      const objectUrl = `${storageBase(supabaseUrl)}/${MIRROR_BUCKET}/${objectKey}`;
      const res = await fetch(objectUrl, {
        headers: { apikey: anonKey, Authorization: session.auth },
      });
      if (!res.ok) {
        return jsonResponse({ error: "Artifact not found" }, res.status === 404 ? 404 : 502, request);
      }
      const text = await res.text();
      try {
        return jsonResponse(JSON.parse(text), 200, request);
      } catch {
        return new Response(text, {
          status: 200,
          headers: { ...corsHeaders(request), "Content-Type": "application/json; charset=utf-8" },
        });
      }
    }

    const listUrl = `${supabaseUrl.replace(/\/$/, "")}/storage/v1/object/list/${MIRROR_BUCKET}`;
    const listRes = await fetch(listUrl, {
      method: "POST",
      headers: {
        apikey: anonKey,
        Authorization: session.auth,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ prefix, limit: 200, offset: 0 }),
    });
    if (!listRes.ok) {
      return jsonResponse({ error: "Could not list mirror" }, 502, request);
    }
    const rows = await listRes.json();
    const artifacts = Array.isArray(rows)
      ? rows
          .filter((row) => row && row.name && !String(row.name).endsWith("/"))
          .map((row) => ({
            path: row.name,
            id: row.id,
            updated_at: row.updated_at,
            metadata: row.metadata,
          }))
      : [];
    return jsonResponse({ artifacts, profile: profileId }, 200, request);
  },
};
