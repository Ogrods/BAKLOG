// Vercel serverless: read-only Pro cloud mirror (Supabase Storage).
// GET /api/mirror  -  list artifacts for signed-in Pro user
// GET /api/mirror?path=games_steam.json  -  download one artifact
// GET /api/mirror?profile=default  -  scope list/download to one BAKLOG profile
// Requires BAKLOG_SUPABASE_URL + BAKLOG_SUPABASE_ANON_KEY on Vercel.

import { checkRateLimit } from "./_rate-limit.js";
import {
  ALLOWED_ARTIFACT,
  MIRROR_BUCKET,
  encodeObjectKey,
  isAllowedOrigin,
  isProUser,
  isValidProfileId,
  mergeProfileListRows,
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

function corsHeaders(request) {
  const origin = request.headers.get("Origin") || "";
  const headers = {
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Authorization, Content-Type",
    "Access-Control-Max-Age": "86400",
    "Cache-Control": "private, no-store",
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

async function listStorageObjects({ supabaseUrl, anonKey, auth, prefix, limit = 200 }) {
  const listUrl = `${supabaseUrl.replace(/\/$/, "")}/storage/v1/object/list/${MIRROR_BUCKET}`;
  const listRes = await fetch(listUrl, {
    method: "POST",
    headers: {
      apikey: anonKey,
      Authorization: auth,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ prefix, limit, offset: 0 }),
  });
  if (!listRes.ok) {
    throw new Error("list_failed");
  }
  const rows = await listRes.json();
  return Array.isArray(rows) ? rows : [];
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
    // Library boot fetches list + one GET per catalog artifact (often 20+).
    const rate = await checkRateLimit(ip, { namespace: "mirror", max: 120 });
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
        const detail =
          res.status === 404
            ? "Artifact not found"
            : res.status >= 500
              ? "Storage upstream error"
              : "Could not download artifact";
        return jsonResponse({ error: detail }, res.status === 404 ? 404 : 502, request);
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
        const topRows = await listStorageObjects({
          supabaseUrl,
          anonKey,
          auth: session.auth,
          prefix: `${userId}/${profileId}/`,
        });
        const dataRows = await listStorageObjects({
          supabaseUrl,
          anonKey,
          auth: session.auth,
          prefix: `${userId}/${profileId}/data/`,
        });
        artifacts = mergeProfileListRows(topRows, dataRows, profileId);
        profiles = [profileId];
      } else {
        // Non-recursive: list user root (profile folders), then each profile + data/.
        const rootRows = await listStorageObjects({
          supabaseUrl,
          anonKey,
          auth: session.auth,
          prefix: `${userId}/`,
        });
        const profileIds = [];
        for (const row of rootRows) {
          const name = String(row?.name || "").trim().replace(/^\/+/, "");
          if (!name || name.includes("/")) continue;
          if (!isValidProfileId(name)) continue;
          profileIds.push(name);
        }
        const collected = [];
        for (const pid of profileIds) {
          const topRows = await listStorageObjects({
            supabaseUrl,
            anonKey,
            auth: session.auth,
            prefix: `${userId}/${pid}/`,
          });
          const dataRows = await listStorageObjects({
            supabaseUrl,
            anonKey,
            auth: session.auth,
            prefix: `${userId}/${pid}/data/`,
          });
          collected.push(...mergeProfileListRows(topRows, dataRows, pid));
        }
        // Also accept any already-flattened rows under userId/ (legacy).
        const parsed = parseMirrorListRows(rootRows, userId);
        const seen = new Set(collected.map((a) => `${a.profile}:${a.path}`));
        for (const row of parsed.artifacts) {
          const key = `${row.profile}:${row.path}`;
          if (!seen.has(key)) collected.push(row);
        }
        artifacts = collected.sort(
          (a, b) =>
            (a.profile || "").localeCompare(b.profile || "") ||
            (a.path || "").localeCompare(b.path || ""),
        );
        profiles = [...new Set(artifacts.map((a) => a.profile).filter(Boolean))].sort();
      }

      return jsonResponse({ artifacts, profiles, profile: profileId || null }, 200, request);
    } catch {
      return jsonResponse({ error: "Could not list mirror" }, 502, request);
    }
  },
};
