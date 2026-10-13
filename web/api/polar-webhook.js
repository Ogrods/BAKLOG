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
// query param) is treated as the Supabase user id; when it is missing or not a
// real user we match the buyer by email via the get_user_id_by_email RPC (see
// web/sql/polar_entitlement.sql). Entitlement rules (paid flag, beta-day credit,
// out-of-order events) live in _polar-pending.js applyPaidEntitlement. Every
// matched change emails the founder.
// Unmatched buyers are stored in polar_pending_entitlements (applied on signup by
// auth-signup-notify.js) and the founder is emailed (RESEND_API_KEY, NOTIFY_FROM,
// NOTIFY_TO; optional - storage still happens without them).

import { notifyFounder } from "./_notify.js";
import { normEmail, setUserPlan, upsertPendingEntitlement } from "./_polar-pending.js";

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

function polarIds(event) {
  const data = event?.data || {};
  const isSubscription = String(event?.type || "").startsWith("subscription.");
  return {
    customerId: String(data.customer_id || data.customer?.id || ""),
    subscriptionId: String((isSubscription ? data.id : data.subscription_id) || ""),
  };
}

async function handleUnmatchedBuyer({ url, key, event, email, plan }) {
  const addr = normEmail(email);
  const type = event?.type || "unknown";
  let stored = false;
  if (addr) {
    const { customerId, subscriptionId } = polarIds(event);
    await upsertPendingEntitlement({
      url,
      key,
      email: addr,
      plan,
      eventType: type,
      customerId,
      subscriptionId,
    });
    stored = true;
  }
  await notifyFounder({
    subject: `Unmatched Polar buyer: ${addr || "(no email)"} (${type})`,
    replyTo: addr || undefined,
    text: [
      "A Polar event matched no BAKLOG account.",
      "",
      `Event: ${type}`,
      `Buyer email: ${addr || "(none on event)"}`,
      `Plan to apply: ${plan}`,
      stored
        ? "Saved to polar_pending_entitlements. Pro applies automatically when an account with this email is created."
        : "Not saved (no email on event). Grant manually with scripts/grant_beta_pro.py.",
    ].join("\n"),
  });
  return stored;
}

function eventTimestamp(event) {
  const data = event?.data || {};
  return String(data.modified_at || data.created_at || event?.timestamp || "");
}

async function findUserIdByEmail({ url, key, email }) {
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

function fmtMeta(meta) {
  const parts = [`plan=${meta?.plan || "free"}`];
  if (meta?.paid) parts.push(`paid since ${meta.paid_since || "?"}`);
  if (meta?.comp_until) parts.push(`comp_until ${meta.comp_until}`);
  return parts.join(", ");
}

async function notifyEntitlementChange({ event, result }) {
  const type = event?.type || "unknown";
  const email = result.email || "(unknown email)";
  await notifyFounder({
    subject: `Polar ${type}: ${email} now ${result.plan}`,
    replyTo: result.email || undefined,
    text: [
      "A Polar event changed a BAKLOG account.",
      "",
      `Event: ${type}`,
      `Account: ${email}`,
      `Before: ${fmtMeta(result.before)}`,
      `After: ${fmtMeta(result.after)}`,
      ...(result.creditedDays
        ? [`Credited ${result.creditedDays} unused beta day(s); Pro now runs through ${result.after.comp_until}.`]
        : []),
    ].join("\n"),
  });
}

/**
 * Match the buyer and write the entitlement. A checkout external_id that is not a
 * real user falls back to the email lookup. Returns null when nothing matched.
 */
async function applyToMatchedUser({ url, key, externalId, email, plan, eventAt }) {
  if (externalId && UUID_RE.test(externalId)) {
    try {
      return await setUserPlan({ url, key, userId: externalId, plan, eventAt });
    } catch (err) {
      if (err?.status !== 404) throw err;
      console.warn("polar-webhook: external_id is not a Supabase user; trying email");
    }
  }
  const userId = await findUserIdByEmail({ url, key, email });
  if (!userId) return null;
  // Same rule as the pending path: an email match only counts once that email is confirmed.
  return setUserPlan({ url, key, userId, plan, eventAt, requireConfirmed: true });
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
    let result;
    try {
      result = await applyToMatchedUser({
        url,
        key,
        externalId,
        email,
        plan: entitlement.plan,
        eventAt: eventTimestamp(event),
      });
    } catch (err) {
      console.error("polar-webhook: matching or setting plan failed", err);
      return Response.json({ error: "Update failed" }, { status: 500 });
    }

    if (!result) {
      // No matching BAKLOG account (buyer used a different email, or has no account
      // yet). Store the entitlement so signup applies it, and alert the founder.
      // A storage failure returns 500 so Polar retries.
      console.warn(`polar-webhook: no Supabase user for event ${event?.type} (unmatched buyer)`);
      let stored;
      try {
        stored = await handleUnmatchedBuyer({ url, key, event, email, plan: entitlement.plan });
      } catch (err) {
        console.error("polar-webhook: storing unmatched buyer failed", err);
        return Response.json({ error: "Pending store failed" }, { status: 500 });
      }
      return Response.json({ ok: true, matched: false, pending: stored }, { status: 202 });
    }

    if (result.stale) {
      console.warn(`polar-webhook: ignored out-of-order ${event?.type}`);
      return Response.json({ ok: true, stale: true }, { status: 202 });
    }

    await notifyEntitlementChange({ event, result });
    console.log(`polar-webhook: ${event?.type} -> plan=${result.plan}`);
    return Response.json(
      { ok: true, plan: result.plan, creditedDays: result.creditedDays },
      { status: 202 },
    );
  },
};
