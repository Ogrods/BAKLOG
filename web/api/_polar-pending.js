// Supabase service-role helpers for Pro entitlements (polar-webhook + auth-signup-notify).
// Table: web/sql/polar_pending_entitlements.sql.

const TABLE = "polar_pending_entitlements";

function serviceHeaders(key, extra = {}) {
  return {
    apikey: key,
    Authorization: `Bearer ${key}`,
    "Content-Type": "application/json",
    ...extra,
  };
}

export function normEmail(email) {
  return String(email || "").trim().toLowerCase();
}

export async function setUserPlan({ url, key, userId, plan }) {
  const getR = await fetch(`${url}/auth/v1/admin/users/${userId}`, {
    headers: { apikey: key, Authorization: `Bearer ${key}` },
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
    headers: serviceHeaders(key),
    body: JSON.stringify({ app_metadata: meta }),
  });
  if (!r.ok) {
    const detail = await r.text().catch(() => "");
    throw new Error(`Supabase admin ${r.status}: ${detail}`);
  }
}

/** Insert or update the pending row for an unmatched buyer (keyed by lowercased email). */
export async function upsertPendingEntitlement({
  url,
  key,
  email,
  plan,
  eventType = "",
  customerId = "",
  subscriptionId = "",
}) {
  const row = {
    email: normEmail(email),
    plan,
    last_event_type: String(eventType || ""),
    polar_customer_id: String(customerId || ""),
    polar_subscription_id: String(subscriptionId || ""),
    updated_at: new Date().toISOString(),
  };
  const r = await fetch(`${url}/rest/v1/${TABLE}?on_conflict=email`, {
    method: "POST",
    headers: serviceHeaders(key, { Prefer: "resolution=merge-duplicates,return=minimal" }),
    body: JSON.stringify(row),
  });
  if (!r.ok) {
    const detail = await r.text().catch(() => "");
    throw new Error(`Supabase pending upsert ${r.status}: ${detail}`);
  }
}

/** Pending row for this email, or null. */
export async function findPendingEntitlement({ url, key, email }) {
  const addr = normEmail(email);
  if (!addr) return null;
  const r = await fetch(
    `${url}/rest/v1/${TABLE}?email=eq.${encodeURIComponent(addr)}&select=*&limit=1`,
    { headers: serviceHeaders(key) },
  );
  if (!r.ok) {
    const detail = await r.text().catch(() => "");
    throw new Error(`Supabase pending lookup ${r.status}: ${detail}`);
  }
  const rows = await r.json().catch(() => []);
  return Array.isArray(rows) && rows.length ? rows[0] : null;
}

export async function markPendingApplied({ url, key, email, userId }) {
  const now = new Date().toISOString();
  const r = await fetch(`${url}/rest/v1/${TABLE}?email=eq.${encodeURIComponent(normEmail(email))}`, {
    method: "PATCH",
    headers: serviceHeaders(key, { Prefer: "return=minimal" }),
    body: JSON.stringify({ applied_at: now, applied_user_id: userId, updated_at: now }),
  });
  if (!r.ok) {
    const detail = await r.text().catch(() => "");
    throw new Error(`Supabase pending mark ${r.status}: ${detail}`);
  }
}
