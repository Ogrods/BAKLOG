/**
 * Global library noise rules — mirrors shared/library_noise.py.
 * Noise rows stay in catalog JSON; the UI auto-hides them (restorable).
 */

const TRADEMARK_RE = /[™®©]/g;

export const NOISE_EXACT_TITLES = new Set([
  "live",
  "hbo max",
  "hbo go",
  "shadow costume for sonic",
  "sonic holiday costume",
  "lego sonic skin",
  "amazon prime video",
  "disney plus",
  "disney",
  "spotify",
  "youtube",
  "twitch",
  "netflix",
  "hulu",
  "watchesn",
  "watchespn",
  "pluto tv",
  "sharefactory",
  "share factory studio",
  "the playroom",
  "project catch",
  "directv nfl sunday ticket",
  "freedom to buy games",
]);

const NOISE_TITLE_PATTERNS = [
  /\btech beta\b/i,
  /\b(pre[- ]game )?editor\b/i,
  /\bresource archiver\b/i,
  /\bcostume for\b/i,
  /\bpublic testing\b/i,
  /\btest branch\b/i,
  /\bpuzzle pack\b/i,
  /\bglove skin\b/i,
  /\bsoundtrack\b/i,
  /\bwallpaper$/i,
  /\bart book\b/i,
  /\bartbook\b/i,
  /\bdigital art book\b/i,
  /\bmini digital sound\b/i,
  /\bcharacter pack\b/i,
  /\bchallenge pack\b/i,
  /\bpicaro\b/i,
  /\bskin pack\b/i,
  /\bcostume pack\b/i,
  /\bexpansion pass\b/i,
  /\bseason pass\b/i,
  /\bfighter pass\b/i,
  /\badd-?on content\b/i,
  /\bbonus content\b/i,
  /\bupgrade pack\b/i,
  /\bcoin set\b/i,
  /\bnintendo switch online\b/i,
  /\be?shop card\b/i,
  /\badd-on content bundle\b/i,
  /\bcontent$/i,
  /\bpokémon home\b/i,
  /\bpokemon home\b/i,
  /\bpokémon tv\b/i,
  /\bpokemon tv\b/i,
  /\bcrunchyroll\b/i,
  /\binkypen\b/i,
  /\s+beta\s*$/i,
];

const PSN_ENTITLEMENT_ID_RE = /^(?:up\d+-)?(?:cusa|ppsa|npwr)\d+_\d+$/i;

const NINTENDO_EXTRA_TITLE_RE = /\b(dlc|skin|coins?|membership|expansion pack)\b/i;

const PSN_EXTRA_TITLE_PATTERNS = [
  /\bdemo\b/i,
  /\bopen beta\b/i,
  /\bbeta\b/i,
  /\bb e t a\b/i,
  /\btrial version\b/i,
  /\bdigital deluxe soundtrack\b/i,
  /^dlc\b/i,
  /\btrophy set$/i,
  /\btrophies$/i,
  /\btheme$/i,
  /\bdynamic theme$/i,
  /\bavatar pack\b/i,
];

const GOG_DLC_RE = /\bDLC\b/i;

const EDITION_SUFFIXES = [
  " digital deluxe edition",
  " deluxe edition",
  " gold edition",
  " ultimate edition",
  " complete edition",
  " definitive edition",
  " special edition",
  " collectors edition",
  " collector's edition",
];

const EDITION_VARIANT_SUBTITLE_RE = /\b(edition|deluxe|upgrade|complete|musical|trilogy|collection|pack|bundle|goty|definitive|remastered|remaster|ultimate)\b/i;

/** @deprecated use NOISE_EXACT_TITLES — kept for tests importing JUNK_NAMES */
export const JUNK_NAMES = NOISE_EXACT_TITLES;

export function normalizeNoiseTitle(name) {
  return String(name || "")
    .replace(TRADEMARK_RE, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export function isEntitlementSlug(name) {
  const s = String(name || "").trim();
  return Boolean(s) && s.includes("_") && !/\s/.test(s);
}

export function isPsnEntitlementId(name) {
  return PSN_ENTITLEMENT_ID_RE.test(String(name || "").trim());
}

export function shouldAutoHideByTitle(name) {
  const raw = String(name || "").trim();
  if (!raw) return true;
  const norm = normalizeNoiseTitle(raw);
  if (!norm) return true;
  if (NOISE_EXACT_TITLES.has(norm)) return true;
  if (isEntitlementSlug(raw) || isPsnEntitlementId(raw)) return true;
  return NOISE_TITLE_PATTERNS.some((re) => re.test(raw) || re.test(norm));
}

export function shouldAutoHideNintendoTitle(name) {
  const raw = String(name || "").trim();
  if (shouldAutoHideByTitle(raw)) return true;
  return NINTENDO_EXTRA_TITLE_RE.test(raw);
}

export function shouldAutoHidePsnTitle(name) {
  const raw = String(name || "").trim();
  if (!raw) return true;
  if (shouldAutoHideByTitle(raw)) return true;
  const norm = normalizeNoiseTitle(raw);
  return PSN_EXTRA_TITLE_PATTERNS.some((re) => re.test(raw) || re.test(norm));
}

export function shouldAutoHideGogTitle(name) {
  const raw = String(name || "").trim();
  if (shouldAutoHideByTitle(raw)) return true;
  return GOG_DLC_RE.test(raw);
}

export function editionBaseKey(name) {
  let key = normalizeNoiseTitle(name);
  for (const suffix of EDITION_SUFFIXES) {
    if (key.endsWith(suffix)) key = key.slice(0, -suffix.length).trim();
  }
  const raw = String(name || "");
  if (raw.includes(":")) {
    const colonSub = raw.split(":").slice(1).join(":").trim();
    if (colonSub && EDITION_VARIANT_SUBTITLE_RE.test(colonSub)) {
      return normalizeNoiseTitle(raw.split(":")[0]);
    }
  }
  return key;
}

export function isNintendoNoiseRow(g) {
  if (!g) return false;
  if (g.is_dlc || g.nintendo_is_dlc) return true;
  const tags = g.tags || [];
  if (tags.includes("dlc")) {
    const hasApp = Boolean(
      g.has_application
      || g.has_nx_application
      || g.has_ounce_application
      || g.application_id
      || g.nintendo_has_application
      || g.nintendo_has_nx_application
      || g.nintendo_has_ounce_application,
    );
    if (!hasApp) return true;
  }
  return shouldAutoHideNintendoTitle(g.name);
}

/**
 * True when a library row should be auto-hidden (not hard-dropped).
 * itch: classification guardrail only (caller passes itchIsGameFn).
 */
export function shouldAutoHideLibraryRow(g, { itchIsGameFn } = {}) {
  if (!g) return false;
  const store = String(g.store || "").toLowerCase();
  if (store === "itch" && typeof itchIsGameFn === "function" && !itchIsGameFn(g)) {
    return true;
  }
  if (store === "nintendo" && isNintendoNoiseRow(g)) return true;
  if (store === "psn") return shouldAutoHidePsnTitle(g.name);
  if (store === "gog") return shouldAutoHideGogTitle(g.name);
  return shouldAutoHideByTitle(g.name);
}

/** Back-compat alias for isJunkEntry callers during migration. */
export function isJunkEntry(g) {
  return shouldAutoHideByTitle(g?.name);
}
