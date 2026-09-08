// Distributed rate limiting for landing serverless APIs (Vercel KV / Upstash).
// Falls back to in-memory buckets in dev/test when KV creds are absent.

const RATE_WINDOW_MS = 60_000;
/** Default max for write-ish / abuse-sensitive endpoints (subscribe, report, metrics). */
const RATE_MAX = 5;

/** @type {Map<string, { start: number, count: number }>} */
const memoryBuckets = new Map();

/** @type {Map<string, import("@upstash/ratelimit").Ratelimit>} */
const kvLimiters = new Map();

let loggedMemoryFallback = false;

function kvCredentials() {
  const url = process.env.KV_REST_API_URL || process.env.UPSTASH_REDIS_REST_URL;
  const token = process.env.KV_REST_API_TOKEN || process.env.UPSTASH_REDIS_REST_TOKEN;
  if (!url || !token) return null;
  return { url, token };
}

function isProductionWithoutKv() {
  return process.env.VERCEL_ENV === "production" && !kvCredentials();
}

function isRateLimitedInMemory(ip, namespace, max) {
  const key = `${namespace}:${max}:${ip}`;
  const now = Date.now();
  let entry = memoryBuckets.get(key);
  if (!entry || now - entry.start > RATE_WINDOW_MS) {
    entry = { start: now, count: 0 };
    memoryBuckets.set(key, entry);
  }
  entry.count += 1;
  if (memoryBuckets.size > 10_000) {
    for (const [bucketKey, bucket] of memoryBuckets) {
      if (now - bucket.start > RATE_WINDOW_MS) memoryBuckets.delete(bucketKey);
    }
  }
  return entry.count > max;
}

async function getKvLimiter(namespace, max) {
  const cacheKey = `${namespace}:${max}`;
  let limiter = kvLimiters.get(cacheKey);
  if (limiter) return limiter;

  const creds = kvCredentials();
  if (!creds) return null;

  const [{ Ratelimit }, { Redis }] = await Promise.all([
    import("@upstash/ratelimit"),
    import("@upstash/redis"),
  ]);

  const redis = new Redis({ url: creds.url, token: creds.token });
  limiter = new Ratelimit({
    redis,
    limiter: Ratelimit.slidingWindow(max, `${RATE_WINDOW_MS} ms`),
    // Include max in prefix so raising a limit does not reuse a stale low bucket.
    prefix: `${namespace}:rate:${max}`,
  });
  kvLimiters.set(cacheKey, limiter);
  return limiter;
}

/**
 * @param {string} ip
 * @param {{ namespace?: string, max?: number }} [options]
 * @returns {Promise<{ limited: boolean, misconfigured: boolean }>}
 */
export async function checkRateLimit(ip, { namespace = "default", max = RATE_MAX } = {}) {
  const limit = Number.isFinite(max) && max > 0 ? Math.floor(max) : RATE_MAX;

  if (isProductionWithoutKv()) {
    return { limited: false, misconfigured: true };
  }

  const limiter = await getKvLimiter(namespace, limit);
  if (!limiter) {
    if (!loggedMemoryFallback) {
      console.warn("rate-limit: using in-memory fallback");
      loggedMemoryFallback = true;
    }
    return { limited: isRateLimitedInMemory(ip, namespace, limit), misconfigured: false };
  }

  const { success } = await limiter.limit(ip);
  return { limited: !success, misconfigured: false };
}
