// Vercel serverless function: receives Polar (polar.sh) subscription webhooks and
// flips the buyer's BAKLOG entitlement by writing app_metadata.plan on their
// Supabase user. shared/supabase_auth.py reads that signed claim from the JWT so
// the local server resolves is_pro() without any BAKLOG-hosted session state.
//
// Polar follows the Standard Webhooks spec (HMAC-SHA256). We verify the signature
// with Web Crypto (no extra dependency) to match the other dependency-free funcs.
//
// Required env vars:
//   POLAR_WEBHOOK_SECRET        - the signing secret from the Polar webhook endpoint
//   SUPABASE_URL                - https://<ref>.supabase.co
//   SUPABASE_SERVICE_ROLE_KEY   - service_role key (GoTrue admin + rpc)
//
// Buyer matching: the Polar customer's external_id (when passed as a checkout
// query param) is treated as the Supabase user id; otherwise we match the buyer
// by email via the get_user_id_by_email RPC (see landing/sql/polar_entitlement.sql).

const TIMESTAMP_TOLERANCE_SEC = 5 * 60;
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const PRO_ALIASES = new Set(["pro", "paid", "premium"]);

function bytesToBase64(bytes) {
  let binary = "";
  for (const b of bytes) binary += String.fromCharCode(b);
  return btoa(binary);
}

function base64ToBytes(b64) {
  const binary = atob(b64);
  const out = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) out[i] = binary.charCodeAt(i);
  return out;
}

// Standard Webhooks signing key. Polar hands you a raw secret string (e.g.
// "polar_whs_..."); the spec's whsec_-prefixed form carries a base64 key. Support
// both: strip a whsec_ prefix and base64-decode it, else use the raw UTF-8 bytes.
function signingKeyBytes(secret) {
  const trimmed = (secret || "").trim();
  if (trimmed.startsWith("whsec_")) {
    try {
      return base64ToBytes(trimmed.slice("whsec_".length));
    } catch {
      /* fall through to raw bytes */
    }
  }
  return new TextEncoder().encode(trimmed);
}

function constantTimeEqual(a, b) {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i += 1) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

async function verifySignature({ secret, id, timestamp, signatureHeader, body }) {
  if (!secret || !id || !timestamp || !signatureHeader) return false;

  const ts = Number(timestamp);
  if (!Number.isFinite(ts)) return false;
  if (Math.abs(Date.now() / 1000 - ts) > TIMESTAMP_TOLERANCE_SEC) return false;

  const key = await crypto.subtle.importKey(
    "raw",
    signingKeyBytes(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signed = `${id}.${timestamp}.${body}`;
  const mac = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(signed));
  const expected = bytesToBase64(new Uint8Array(mac));

  // Header is a space-delimited list of "<version>,<base64sig>" entries.
  return signatureHeader.split(" ").some((part) => {
    const comma = part.indexOf(",");
    const sig = comma === -1 ? part : part.slice(comma + 1);
    return constantTimeEqual(sig, expected);
  });
}

function planFromProduct(product) {
  const raw = product?.metadata?.plan;
  if (typeof raw === "string" && PRO_ALIASES.has(raw.trim().toLowerCase())) return "pro";
  return "pro"; // single paid product: default to pro even if metadata is missing
}

// Map a Polar event to the entitlement we should write, or null to ignore it.
function resolveEntitlement(event) {
  const data = event?.data || {};
  switch (event?.type) {
    case "subscription.active":
    case "subscription.uncanceled":
      return { plan: planFromProduct(data.product) };
    case "subscription.updated":
      // "canceled" keeps access until period end; only a non-active status drops it.
      return data.status === "active"
        ? { plan: planFromProduct(data.product) }
        : data.status && data.status !== "trialing"
          ? { plan: "free" }
          : null;
    case "subscription.revoked":
      return { plan: "free" };
    case "order.paid":
      // Covers the initial paid order (and one-off purchases, if ever added).
      return { plan: planFromProduct(data.product) };
    case "order.refunded":
      return { plan: "free" };
    default:
      return null; // created/canceled/etc. are no-ops for entitlement
  }
}

function buyerRef(event) {
  const data = event?.data || {};
  const customer = data.customer || data.user || {};
  const externalId =
    customer.external_id || data.external_customer_id || data.customer_external_id || "";
  const email = customer.email || data.customer_email || data.user?.email || "";
  return { externalId: String(externalId || "").trim(), email: String(email || "").trim() };
}

async function findSupabaseUserId({ url, key, externalId, email }) {
  if (externalId && UUID_RE.test(externalId)) return externalId;
  if (!email) return null;
  const r = await fetch(`${url}/rest/v1/rpc/get_user_id_by_email`, {
    method: "POST",
    headers: {
      apikey: key,
      Authorization: `Bearer ${key}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ input_email: email }),
  });
  if (!r.ok) {
    const detail = await r.text().catch(() => "");
    throw new Error(`Supabase rpc ${r.status}: ${detail}`);
  }
  const out = await r.json().catch(() => null);
  if (typeof out === "string") return out;
  if (Array.isArray(out) && out.length) return out[0]?.id || out[0] || null;
  return out?.id || null;
}

async function setUserPlan({ url, key, userId, plan }) {
  const getR = await fetch(`${url}/auth/v1/admin/users/${userId}`, {
    headers: {
      apikey: key,
      Authorization: `Bearer ${key}`,
    },
  });
  if (!getR.ok) {
    const detail = await getR.text().catch(() => "");
    throw new Error(`Supabase admin GET ${getR.status}: ${detail}`);
  }
  const user = await getR.json().catch(() => ({}));
  const meta = { ...(user?.app_metadata || {}) };
  meta.plan = plan;
  const r = await fetch(`${url}/auth/v1/admin/users/${userId}`, {
    method: "PUT",
    headers: {
      apikey: key,
      Authorization: `Bearer ${key}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ app_metadata: meta }),
  });
  if (!r.ok) {
    const detail = await r.text().catch(() => "");
    throw new Error(`Supabase admin ${r.status}: ${detail}`);
  }
}

export default {
  async fetch(request) {
    if (request.method !== "POST") {
      return Response.json({ error: "Method not allowed" }, { status: 405 });
    }

    const secret = process.env.POLAR_WEBHOOK_SECRET;
    const url = process.env.SUPABASE_URL;
    const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
    if (!secret || !url || !key) {
      console.error("polar-webhook: missing POLAR_WEBHOOK_SECRET / SUPABASE_URL / SERVICE_ROLE");
      return Response.json({ error: "Server not configured" }, { status: 500 });
    }

    // Raw body is required for signature verification — do not parse first.
    const body = await request.text();
    if (body.length > 1024 * 1024) {
      return Response.json({ error: "Payload too large" }, { status: 413 });
    }
    const ok = await verifySignature({
      secret,
      id: request.headers.get("webhook-id"),
      timestamp: request.headers.get("webhook-timestamp"),
      signatureHeader: request.headers.get("webhook-signature"),
      body,
    });
    if (!ok) {
      return Response.json({ error: "Invalid signature" }, { status: 403 });
    }

    let event;
    try {
      event = JSON.parse(body);
    } catch {
      return Response.json({ error: "Invalid JSON" }, { status: 400 });
    }

    const entitlement = resolveEntitlement(event);
    if (!entitlement) {
      // Acknowledge ignored event types so Polar does not retry them.
      return Response.json({ ok: true, ignored: event?.type || "unknown" }, { status: 202 });
    }

    const { externalId, email } = buyerRef(event);
    let userId;
    try {
      userId = await findSupabaseUserId({ url, key, externalId, email });
    } catch (err) {
      console.error("polar-webhook: user lookup failed", err);
      return Response.json({ error: "Lookup failed" }, { status: 500 });
    }

    if (!userId) {
      // No matching BAKLOG account (buyer used a different email, or has no account
      // yet). Acknowledge so Polar stops retrying; the License Key benefit / manual
      // license.json paste remains the fallback for pure-local buyers.
      console.warn(`polar-webhook: no Supabase user for event ${event?.type} (unmatched buyer)`);
      return Response.json({ ok: true, matched: false }, { status: 202 });
    }

    try {
      await setUserPlan({ url, key, userId, plan: entitlement.plan });
    } catch (err) {
      console.error("polar-webhook: setting plan failed", err);
      return Response.json({ error: "Update failed" }, { status: 500 });
    }

    console.log(`polar-webhook: ${event?.type} -> plan=${entitlement.plan} user=${userId}`);
    return Response.json({ ok: true, plan: entitlement.plan }, { status: 202 });
  },
};
