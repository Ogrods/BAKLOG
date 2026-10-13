// Vercel Cron (daily, see vercel.json): keeps hosted Pro entitlements tidy without
// manual runs of scripts/grant_beta_pro.py --expire.
//
// 1. Comp grants whose app_metadata.comp_until has passed (and are not paid) drop
//    to plan=free; comp_until is removed, matching grant_beta_pro.py --expire.
// 2. Pending Polar purchases (polar_pending_entitlements) are applied to accounts
//    with the same email once that email is confirmed.
// The founder gets a summary email when anything changed.
//
// Required env vars:
//   CRON_SECRET                 - Vercel sends it as "Authorization: Bearer <CRON_SECRET>"
//   SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
// Optional: RESEND_API_KEY, NOTIFY_FROM, NOTIFY_TO (summary email)

import { notifyFounder } from "./_notify.js";
import {
  compExpired,
  expireCompMeta,
  getAdminUser,
  listAllUsers,
  listUnappliedPendingPro,
  markPendingApplied,
  normEmail,
  putAppMetadata,
  setUserPlan,
} from "./_polar-pending.js";

function constantTimeEqual(a, b) {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i += 1) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

function authorized(request) {
  const secret = (process.env.CRON_SECRET || "").trim();
  if (!secret) return false;
  const header = request.headers.get("authorization") || "";
  return constantTimeEqual(header, `Bearer ${secret}`);
}

async function expireComps({ url, key, users, now }) {
  const expired = [];
  for (const user of users) {
    if (!compExpired(user?.app_metadata || {}, now)) continue;
    // A Polar webhook may have changed this user since the list was fetched.
    const fresh = await getAdminUser({ url, key, userId: user.id });
    const meta = fresh?.app_metadata || {};
    if (!compExpired(meta, now)) continue;
    const prevUntil = meta.comp_until;
    await putAppMetadata({ url, key, userId: user.id, meta: expireCompMeta(meta) });
    expired.push(`${user.email || user.id} (comp ended ${prevUntil})`);
  }
  return expired;
}

async function applyConfirmedPending({ url, key, users }) {
  const rows = await listUnappliedPendingPro({ url, key });
  if (!rows.length) return [];
  const byEmail = new Map(users.map((u) => [normEmail(u.email), u]));
  const applied = [];
  for (const row of rows) {
    const user = byEmail.get(normEmail(row.email));
    if (!user || !user.email_confirmed_at) continue;
    await setUserPlan({ url, key, userId: user.id, plan: "pro" });
    await markPendingApplied({ url, key, email: row.email, userId: user.id });
    applied.push(user.email);
  }
  return applied;
}

export default {
  async fetch(request) {
    if (!authorized(request)) {
      return Response.json({ error: "Unauthorized" }, { status: 401 });
    }
    const url = (process.env.SUPABASE_URL || "").trim().replace(/\/+$/, "");
    const key = (process.env.SUPABASE_SERVICE_ROLE_KEY || "").trim();
    if (!url || !key) {
      console.error("comp-expire: missing SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY");
      return Response.json({ error: "Server not configured" }, { status: 500 });
    }

    const now = new Date();
    let expired;
    let applied;
    try {
      const users = await listAllUsers({ url, key });
      expired = await expireComps({ url, key, users, now });
      applied = await applyConfirmedPending({ url, key, users });
    } catch (err) {
      console.error("comp-expire: run failed", err);
      await notifyFounder({
        subject: "BAKLOG comp-expire cron FAILED",
        text: `The daily Pro cron failed: ${err?.message || err}\nRun scripts/grant_beta_pro.py --expire manually if needed.`,
      });
      return Response.json({ error: "Run failed" }, { status: 500 });
    }

    if (expired.length || applied.length) {
      await notifyFounder({
        subject: `BAKLOG Pro cron: ${expired.length} expired, ${applied.length} pending applied`,
        text: [
          "Daily Pro maintenance changed these accounts.",
          "",
          ...(expired.length ? ["Comp Pro ended (now free):", ...expired.map((e) => `  ${e}`), ""] : []),
          ...(applied.length ? ["Pending Polar purchase applied:", ...applied.map((e) => `  ${e}`)] : []),
        ].join("\n"),
      });
    }
    return Response.json({ ok: true, expired: expired.length, applied: applied.length });
  },
};
