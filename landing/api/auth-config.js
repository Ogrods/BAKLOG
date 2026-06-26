// Vercel serverless: public Supabase client config for hosted auth pages (anon key only).
// Requires BAKLOG_SUPABASE_URL + BAKLOG_SUPABASE_ANON_KEY (or SUPABASE_URL + anon key).
// Production also requires KV_REST_API_* or UPSTASH_REDIS_REST_* (distributed rate limit).

import { checkRateLimit } from "./_rate-limit.js";

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

export default {
  async fetch(request) {
    if (request.method !== "GET") {
      return Response.json({ error: "Method not allowed" }, { status: 405 });
    }

    const ip = clientIp(request);
    const rate = await checkRateLimit(ip, { namespace: "auth-config" });
    if (rate.misconfigured) {
      console.error("auth-config: missing KV rate-limit credentials in production");
      return Response.json({ error: "Server not configured" }, { status: 503 });
    }
    if (rate.limited) {
      return Response.json({ error: "Too many requests" }, {
        status: 429,
        headers: { "Retry-After": "60" },
      });
    }

    const supabaseUrl = pickEnv("BAKLOG_SUPABASE_URL", "SUPABASE_URL");
    const supabaseAnonKey = pickEnv("BAKLOG_SUPABASE_ANON_KEY", "SUPABASE_ANON_KEY");
    if (!supabaseUrl || !supabaseAnonKey) {
      return Response.json({ error: "Auth not configured" }, { status: 503 });
    }
    return Response.json(
      { supabaseUrl, supabaseAnonKey },
      {
        status: 200,
        headers: {
          "Cache-Control": "public, max-age=300",
        },
      },
    );
  },
};
