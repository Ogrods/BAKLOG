// Vercel serverless: read-only Pro cloud mirror (Supabase Storage).
// GET /api/mirror — list artifacts for signed-in Pro user
// GET /api/mirror?path=games_steam.json — download one artifact
// GET /api/mirror?profile=default — scope list/download to one BAKLOG profile
// Requires BAKLOG_SUPABASE_URL + BAKLOG_SUPABASE_ANON_KEY on Vercel.

import { checkRateLimit } from "./_rate-limit.js";
import {
  ALLOWED_ARTIFACT,
  MIRROR_BUCKET,
  encodeObjectKey,
  isProUser,
  isValidProfileId,
  normalizeProfileId,
  parseMirrorListRows,
  pickEnv,
  resolveArtifactProfile,
  storageBase,
} from "./_mirror-helpers.js";

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

async function verifySession(request, supabaseUrl, anonKey) {
  const auth = request.headers.get("Authorization") || "";
  if (!auth.startsWith("Bearer ")) return null;
  const res = await fetch(`${supabaseUrl}/auth/v1/user`, {
    headers: { apikey: anonKey, Authorization: auth },
  });
  if (!res.ok) return null;
  const user = await res.json();
  if (!isProUser(user)) return null;
  return { auth, user };
}

async function listStorageObjects({ supabaseUrl, anonKey, auth, prefix, pageSize = 200 }) {
  const listUrl = `${supabaseUrl.replace(/\/$/, "")}/storage/v1/object/list/${MIRROR_BUCKET}`;
  const rows = [];
  let offset = 0;
  while (true) {
    const listRes = await fetch(listUrl, {
      method: "POST",
      headers: {
        apikey: anonKey,
        Authorization: auth,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ prefix, limit: pageSize, offset }),
    });
    if (!listRes.ok) {
      throw new Error("list_failed");
    }
    const chunk = await listRes.json();
    const page = Array.isArray(chunk) ? chunk : [];
    if (!page.length) break;
    rows.push(...page);
    if (page.length < pageSize) break;
    offset += pageSize;
  }
  return rows;
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
    const profileParam = (url.searchParams.get("profile") || "").trim();
    const artifact = (url.searchParams.get("path") || "").trim();

    let profileId = "";
    if (profileParam) {
      if (!isValidProfileId(profileParam)) {
        return jsonResponse({ error: "Invalid profile id" }, 400, request);
      }
      profileId = normalizeProfileId(profileParam);
    }

    if (artifact) {
      if (!ALLOWED_ARTIFACT.test(artifact)) {
        return jsonResponse({ error: "Invalid artifact path" }, 400, request);
      }

      let resolvedProfile = profileId;
      if (!resolvedProfile) {
        try {
          const rows = await listStorageObjects({
            supabaseUrl,
            anonKey,
            auth: session.auth,
            prefix: `${userId}/`,
          });
          const parsed = parseMirrorListRows(rows, userId);
          resolvedProfile = resolveArtifactProfile(parsed.artifacts, artifact, userId);
        } catch {
          return jsonResponse({ error: "Could not list mirror" }, 502, request);
        }
        if (!resolvedProfile) {
          return jsonResponse({ error: "Artifact not found" }, 404, request);
        }
      }

      const objectKey = `${userId}/${resolvedProfile}/${artifact}`;
      const objectUrl = `${storageBase(supabaseUrl)}/${MIRROR_BUCKET}/${encodeObjectKey(objectKey)}`;
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

    try {
      let artifacts = [];
      let profiles = [];

      if (profileId) {
        const rows = await listStorageObjects({
          supabaseUrl,
          anonKey,
          auth: session.auth,
          prefix: `${userId}/${profileId}/`,
        });
        artifacts = rows
          .filter((row) => row && row.name && !String(row.name).endsWith("/"))
          .map((row) => ({
            path: String(row.name).trim().replace(/^\/+/, ""),
            profile: profileId,
            id: row.id,
            updated_at: row.updated_at,
            metadata: row.metadata,
          }))
          .filter((row) => ALLOWED_ARTIFACT.test(row.path));
        profiles = [profileId];
      } else {
        const rows = await listStorageObjects({
          supabaseUrl,
          anonKey,
          auth: session.auth,
          prefix: `${userId}/`,
        });
        const parsed = parseMirrorListRows(rows, userId);
        artifacts = parsed.artifacts;
        profiles = parsed.profiles;
      }

      return jsonResponse({ artifacts, profiles, profile: profileId || null }, 200, request);
    } catch {
      return jsonResponse({ error: "Could not list mirror" }, 502, request);
    }
  },
};
