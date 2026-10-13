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

const DAY_MS = 24 * 60 * 60 * 1000;
const ISO_DAY_RE = /^\d{4}-\d{2}-\d{2}$/;

function isoDay(now) {
  return now.toISOString().slice(0, 10);
}

function validDay(raw) {
  const day = String(raw || "").trim().slice(0, 10);
  return ISO_DAY_RE.test(day) ? day : "";
}

function daysBetween(fromDay, toDay) {
  return Math.round((Date.parse(`${toDay}T00:00:00Z`) - Date.parse(`${fromDay}T00:00:00Z`)) / DAY_MS);
}

function addDays(day, n) {
  return isoDay(new Date(Date.parse(`${day}T00:00:00Z`) + n * DAY_MS));
}

/** True while a comp grant (app_metadata.comp_until, YYYY-MM-DD) still covers today (UTC). */
export function compActive(meta, now = new Date()) {
  const day = validDay(meta?.comp_until);
  return Boolean(day) && day >= isoDay(now);
}

/**
 * Pure entitlement transition for a paid Polar event (see grant_beta_pro.py for comps).
 *
 * pro:  plan=pro, paid=true; paid_since is stamped on the first paid event only.
 * free: unused comp days at payment time (comp_until - paid_since) are credited
 *       from today, so beta testers who paid keep the free time they skipped.
 *       Pro stays on while the (possibly extended) comp_until covers today.
 * eventAt: events older than meta.polar_event_at are stale and change nothing.
 */
export function applyPaidEntitlement(meta, plan, { eventAt = "", now = new Date() } = {}) {
  const before = { ...(meta || {}) };
  const lastAt = Date.parse(before.polar_event_at || "");
  const thisAt = Date.parse(eventAt || "");
  if (Number.isFinite(lastAt) && Number.isFinite(thisAt) && thisAt < lastAt) {
    return { meta: before, stale: true, creditedDays: 0 };
  }
  const next = { ...before };
  if (Number.isFinite(thisAt)) next.polar_event_at = new Date(thisAt).toISOString();
  const today = isoDay(now);
  let creditedDays = 0;
  if (plan === "pro") {
    if (!next.paid || !validDay(next.paid_since)) next.paid_since = today;
    next.paid = true;
    next.plan = "pro";
  } else {
    const compUntil = validDay(next.comp_until);
    const paidSince = validDay(next.paid_since);
    if (next.paid && compUntil && paidSince) {
      const leftover = Math.max(0, daysBetween(paidSince, compUntil));
      const credited = addDays(today, leftover);
      if (leftover > 0 && credited > compUntil) {
        next.comp_until = credited;
        creditedDays = leftover;
      }
    }
    delete next.paid;
    delete next.paid_since;
    next.plan = compActive(next, now) ? "pro" : "free";
  }
  return { meta: next, stale: false, creditedDays };
}

/** Comp that has run out: not paid and comp_until before today (matches grant_beta_pro.py --expire). */
export function compExpired(meta, now = new Date()) {
  if (meta?.paid) return false;
  const day = validDay(meta?.comp_until);
  return Boolean(day) && day < isoDay(now);
}

/** Metadata after the daily cron expires a comp: plan=free, comp_until removed. */
export function expireCompMeta(meta) {
  const next = { ...(meta || {}), plan: "free" };
  delete next.comp_until;
  return next;
}

export class SupabaseAdminError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

export async function getAdminUser({ url, key, userId }) {
  const r = await fetch(`${url}/auth/v1/admin/users/${userId}`, {
    headers: { apikey: key, Authorization: `Bearer ${key}` },
  });
  if (!r.ok) {
    const detail = await r.text().catch(() => "");
    throw new SupabaseAdminError(`Supabase admin GET ${r.status}: ${detail}`, r.status);
  }
  return r.json().catch(() => ({}));
}

export async function putAppMetadata({ url, key, userId, meta }) {
  const r = await fetch(`${url}/auth/v1/admin/users/${userId}`, {
    method: "PUT",
    headers: serviceHeaders(key),
    body: JSON.stringify({ app_metadata: meta }),
  });
  if (!r.ok) {
    const detail = await r.text().catch(() => "");
    throw new SupabaseAdminError(`Supabase admin ${r.status}: ${detail}`, r.status);
  }
}

/**
 * Apply a paid Polar entitlement to a Supabase user. Throws SupabaseAdminError
 * (status 404 when the user id does not exist). Returns
 * { plan, before, after, email, stale, creditedDays }.
 */
export async function setUserPlan({ url, key, userId, plan, eventAt = "", now = new Date() }) {
  const user = await getAdminUser({ url, key, userId });
  const before = { ...(user?.app_metadata || {}) };
  const result = applyPaidEntitlement(before, plan, { eventAt, now });
  if (!result.stale) {
    await putAppMetadata({ url, key, userId, meta: result.meta });
  }
  return {
    plan: result.meta.plan || "free",
    before,
    after: result.meta,
    email: String(user?.email || ""),
    stale: result.stale,
    creditedDays: result.creditedDays,
  };
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

/** Unapplied pending Pro purchases (for the daily cron). */
export async function listUnappliedPendingPro({ url, key }) {
  const r = await fetch(`${url}/rest/v1/${TABLE}?applied_at=is.null&plan=eq.pro&select=*`, {
    headers: serviceHeaders(key),
  });
  if (!r.ok) {
    const detail = await r.text().catch(() => "");
    throw new Error(`Supabase pending list ${r.status}: ${detail}`);
  }
  const rows = await r.json().catch(() => []);
  return Array.isArray(rows) ? rows : [];
}

/** Every Supabase auth user, paged through the GoTrue admin API. */
export async function listAllUsers({ url, key, perPage = 1000 }) {
  const users = [];
  for (let page = 1; page < 1000; page += 1) {
    const r = await fetch(`${url}/auth/v1/admin/users?page=${page}&per_page=${perPage}`, {
      headers: { apikey: key, Authorization: `Bearer ${key}` },
    });
    if (!r.ok) {
      const detail = await r.text().catch(() => "");
      throw new SupabaseAdminError(`Supabase admin list ${r.status}: ${detail}`, r.status);
    }
    const body = await r.json().catch(() => ({}));
    const batch = Array.isArray(body?.users) ? body.users : [];
    users.push(...batch);
    if (batch.length < perPage) break;
  }
  return users;
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
