/**
 * Metered deep achievement / trophy sync.
 *
 * The free tier shows the cached completion summary (the trophy pill) for free,
 * and grants a small daily allowance of *deep* syncs — a full re-pull of a
 * store's achievement/trophy data, which costs real upstream API calls. Beyond
 * the daily allowance you spend credits (credit packs are a planned purchase).
 * When both are exhausted the action is gated with an honest message; the
 * planned paid tier lifts the cap.
 *
 * Ledger is profile-scoped in localStorage so each connected account meters
 * independently. Nothing here charges money — it's the quota mechanism only.
 */
import { profileScopedStorageKey } from './profiles.js';

const LEDGER_BASE = 'baklog-achievement-meter';
export const FREE_DAILY = 5;

function ledgerKey() {
  return profileScopedStorageKey(LEDGER_BASE);
}

/** Local calendar day (not UTC) so the allowance resets at the user's midnight. */
export function dayKey(now = new Date()) {
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, '0');
  const d = String(now.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

function defaultLedger() {
  return { day: dayKey(), usedToday: 0, credits: 0, history: {} };
}

function sanitize(raw) {
  const base = defaultLedger();
  if (!raw || typeof raw !== 'object') return base;
  return {
    day: typeof raw.day === 'string' ? raw.day : base.day,
    usedToday: Number.isFinite(raw.usedToday) ? Math.max(0, Math.trunc(raw.usedToday)) : 0,
    credits: Number.isFinite(raw.credits) ? Math.max(0, Math.trunc(raw.credits)) : 0,
    history: raw.history && typeof raw.history === 'object' && !Array.isArray(raw.history) ? raw.history : {},
  };
}

function readLedger() {
  let raw = null;
  try {
    raw = JSON.parse(localStorage.getItem(ledgerKey()) || 'null');
  } catch {
    raw = null;
  }
  const ledger = sanitize(raw);
  // Roll the daily allowance over when the calendar day changes.
  const today = dayKey();
  if (ledger.day !== today) {
    ledger.day = today;
    ledger.usedToday = 0;
  }
  return ledger;
}

function writeLedger(ledger) {
  try {
    localStorage.setItem(ledgerKey(), JSON.stringify(ledger));
  } catch {
    /* storage full / disabled — meter degrades to in-memory for this call */
  }
}

/** { freeDaily, usedToday, freeRemaining, credits, lastSyncByTitle }. */
export function meterSummary() {
  const l = readLedger();
  return {
    freeDaily: FREE_DAILY,
    usedToday: l.usedToday,
    freeRemaining: Math.max(0, FREE_DAILY - l.usedToday),
    credits: l.credits,
    lastSyncByTitle: l.history,
  };
}

export function canDeepSync() {
  const s = meterSummary();
  return s.freeRemaining > 0 || s.credits > 0;
}

/**
 * Spend one deep-sync unit (free allowance first, then a credit). Records the
 * sync time for `titleKey` when given. Returns:
 *   { ok: true, source: 'free'|'credit', remaining: {...} }  on success
 *   { ok: false, reason: 'exhausted', remaining: {...} }     when gated
 */
export function consumeDeepSync(titleKey = null) {
  const l = readLedger();
  let source;
  if (l.usedToday < FREE_DAILY) {
    l.usedToday += 1;
    source = 'free';
  } else if (l.credits > 0) {
    l.credits -= 1;
    source = 'credit';
  } else {
    writeLedger(l); // persist any day rollover even on a gated attempt
    return { ok: false, reason: 'exhausted', remaining: summaryFrom(l) };
  }
  if (titleKey) l.history[titleKey] = Date.now();
  writeLedger(l);
  return { ok: true, source, remaining: summaryFrom(l) };
}

/** Add credits (credit-pack purchase — wiring for the planned billing flow). */
export function addCredits(n) {
  const amount = Math.trunc(Number(n));
  if (!Number.isFinite(amount) || amount <= 0) return meterSummary();
  const l = readLedger();
  l.credits += amount;
  writeLedger(l);
  return summaryFrom(l);
}

function summaryFrom(l) {
  return {
    freeDaily: FREE_DAILY,
    usedToday: l.usedToday,
    freeRemaining: Math.max(0, FREE_DAILY - l.usedToday),
    credits: l.credits,
    lastSyncByTitle: l.history,
  };
}

/** Short human label for the popover footer, e.g. "3 free deep syncs left today". */
export function meterLabel() {
  const s = meterSummary();
  if (s.freeRemaining > 0) {
    return `${s.freeRemaining} free deep ${s.freeRemaining === 1 ? 'sync' : 'syncs'} left today`;
  }
  if (s.credits > 0) {
    return `${s.credits} ${s.credits === 1 ? 'credit' : 'credits'} available`;
  }
  return 'Out of deep syncs — paid tier (planned) lifts the cap';
}

/** Test seam: wipe the ledger for the active profile. */
export function _resetMeter() {
  try {
    localStorage.removeItem(ledgerKey());
  } catch {
    /* ignore */
  }
}
