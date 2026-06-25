/**
 * Loading-screen tips for the boot curtain.
 *
 * Tips are grouped by IDEA: each inner array holds 2-3 phrasings that convey
 * the same hint. The rotation shows one phrasing per turn and never repeats the
 * same idea group twice in a row, so the curtain feels varied even on long boots.
 *
 * All monetization / "support the site" ideas collapse into a single
 * rate-limited slot (SUPPORT_SLOT) so they surface about as often as any one
 * feature tip rather than dominating the rotation.
 *
 * A rare easter-egg (RARE_TIPS) shows ~2% of the time.
 *
 * Keep the flattened phrasing list in sync with the inline boot-tip seed list in
 * index.html (body script) - see ALL_TIPS below.
 */

// Feature / UI idea groups. Each inner array = one idea, multiple phrasings.
export const TIP_GROUPS = [
  [
    "BAKLOG shines on a wider screen - give it room to stretch out.",
    "BAKLOG loves elbow room - open it on a wider screen for the full view.",
    "Got a wide screen? BAKLOG uses every pixel of it.",
  ],
  [
    "Watch your spotlight for anything you want to recategorize.",
    "Something in the spotlight feel mislabeled? Click through and fix it.",
    "The dashboard spotlight cycles your games - a quick way to spot ones to recategorize.",
  ],
  [
    "Own a physical copy? Add it manually - track whatever you want.",
    "Got a game off-store or on disc? Use + Add game to include it.",
    "BAKLOG tracks more than store libraries - add any game by hand.",
  ],
  [
    "See a Humble icon but no other store? It may be a DRM-free download from Humble, or a key to redeem elsewhere.",
    "A lone Humble badge can mean a DRM-free download or a key for another store.",
  ],
  [
    "Sort by time played to see what you actually play, then recategorize from there.",
    "Order by playtime to separate the games you finish from the ones you forget.",
  ],
  [
    "Press / to jump straight to the search box.",
    "Hit / anywhere to focus search instantly.",
  ],
  [
    "Highlight a row, then press B, N, P, U, L, F, or S to set its status.",
    "Status in one keystroke: B Backlog, N Next, P Playing, U Unfinished, L Live, F Finished, S Skip.",
  ],
  [
    "Ctrl+Z undoes your last bulk status change or removal.",
    "Made a bulk edit you regret? Ctrl+Z brings it back.",
  ],
  [
    "Turn on Hide duplicates to collapse the same game across stores.",
    "Own a game on two stores? Hide duplicates merges it into one row.",
  ],
  [
    "Click any dashboard chart to drill into those exact games.",
    "Every dashboard chart is a filter - click a slice to see those games.",
  ],
  [
    "Just bought a game? Store APIs can take up to 24 hours to show it.",
    "New purchase not showing yet? Connections can lag up to a day behind the store.",
  ],
  [
    "Co-op data (online, couch, campaign) is hard to pin down. Spot something off? Let us know.",
    "See a wrong co-op tag? Report it from the menu so we can fix it.",
  ],
  [
    "There's more than one back-to-top button.",
    "Scrolled deep? Two different back-to-top buttons can whisk you up.",
  ],
  [
    "Shift+click the Price header to sort by biggest discount first.",
    "Want the steepest sales up top? Shift+click the Price column.",
  ],
  [
    "Use the A-Z rail on the right edge to jump through a long library.",
    "Long backlog? The alphabet rail on the right jumps you to any letter.",
  ],
  [
    "Click a game's cover to browse alternate cover and landscape art.",
  ],
  [
    "Open Columns to reveal hidden stats like Score and Metacritic.",
    "Missing a column? The Columns button shows Score, Metacritic, and more.",
  ],
  [
    "Can't decide? Hit Pick for me for a random game from your backlog.",
    "Shift+click Pick for me to pull from everything, not just your backlog.",
  ],
  [
    "Click a status or store chip above the table to filter instantly.",
    "The chips above your library are one-click filters - combine them freely.",
  ],
  [
    "Cleanup mode surfaces old, low-rated games you never played - easy to skip.",
    "Trim the backlog: Cleanup mode finds stale, unplayed, low-rated entries.",
  ],
  [
    "Change your look from the profile menu - Midnight, Synthwave, Terminal, and more.",
    "Prefer OLED black? Try the Midnight theme in the profile menu.",
  ],
  [
    "Keep separate libraries with profiles - switch them from the header menu.",
    "Share a PC? Give each person their own BAKLOG profile.",
  ],
  [
    "Never miss a free game again - check Claimable Now on your Wishlist.",
    "Free games rotate fast - the Claimable Now feed flags them on your Wishlist.",
  ],
  [
    "The Fetcher log in the header runs a sync and shows what's fresh or stale.",
    "Catalog feeling old? Open the Fetcher log to refresh a specific store.",
  ],
  [
    "Turn on auto-refresh in Connections to keep stores current while BAKLOG is open.",
    "Leave BAKLOG open and it can quietly refresh stores older than a day.",
  ],
  [
    "Add a note to any row - a yellow dot marks games you've annotated.",
    "Jot a reminder on any game; annotated rows get a little yellow dot.",
  ],
  [
    "Back up statuses, notes, and settings - Export personal data in the ⋯ menu.",
    "Moving machines? Export library backup + personal data, then import on the new PC.",
  ],
];

// Monetization / "support the site" ideas. These all share ONE rotation slot
// (SUPPORT_SLOT) so support messaging stays at roughly single-tip frequency.
export const SUPPORT_GROUPS = [
  [
    "Leaving BAKLOG open on the dashboard keeps the spotlight rotating - and helps fund the free tier.",
    "Keep BAKLOG open on the dashboard and the spotlight's sponsored slides help keep the lights on.",
  ],
  [
    "Buying through our affiliate links costs you nothing extra and helps keep BAKLOG running.",
    "Deal links use affiliate URLs when available - same price for you, a little support for us.",
  ],
  [
    "See a labeled Sponsored deal you like? Clicking it funds the free tier - no pressure.",
    "Sponsored cards are clearly marked and optional, but a click helps keep BAKLOG free.",
  ],
  [
    "BAKLOG Pro adds sync and bulk refresh - and nothing free today moves behind it.",
    "Want fewer sponsored slots? BAKLOG Pro is the no-ads path.",
  ],
  [
    "Not in the beta yet? Request an invite at baklog.app - we onboard in small waves.",
    "Know someone who'd love BAKLOG? Send them to baklog.app to grab an invite.",
  ],
  [
    "Want to help without spending? Toggle Share anonymous usage counts in Connections.",
    "Sharing anonymous usage counts (off by default) helps fund BAKLOG - no library data leaves your machine.",
  ],
  [
    "Hit a bug? Report it from the menu - nothing is sent until you confirm.",
    "Join the Discord to swap tips with other testers and the maintainer.",
  ],
];

export const RARE_TIPS = [
  "My backlog is bigger than yours.",
  "Backlog zero is a myth. Keep climbing.",
];
export const RARE_CHANCE = 0.02;

// Flattened phrasing list (feature + support), excluding rare easter-eggs.
// Mirror this in the inline boot-tip seed list in index.html.
export const ALL_TIPS = [
  ...TIP_GROUPS.flat(),
  ...SUPPORT_GROUPS.flat(),
];

// Sentinel slot key shared by every support phrasing.
const SUPPORT_SLOT = "\u0000support-slot";

// Map each phrasing to its rotation slot: a feature group index, or SUPPORT_SLOT.
const TEXT_TO_SLOT = new Map();
TIP_GROUPS.forEach((group, i) => {
  group.forEach(tip => TEXT_TO_SLOT.set(tip, i));
});
SUPPORT_GROUPS.forEach(group => {
  group.forEach(tip => TEXT_TO_SLOT.set(tip, SUPPORT_SLOT));
});

// Selectable slots: one per feature idea, plus a single shared support slot.
const SLOT_KEYS = [...TIP_GROUPS.map((_, i) => i), SUPPORT_SLOT];

const TIP_INTERVAL_MS = 4000;
const TIP_FADE_MS = 300;

let _tipTimer = null;
let _tipFadeTimer = null;
let _currentTip = null;

function prefersReducedMotion() {
  return (
    typeof matchMedia === "function" &&
    matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

function bootCurtainActive() {
  return (
    typeof document !== "undefined" &&
    document.documentElement?.hasAttribute("data-boot-loading")
  );
}

function randomOf(arr) {
  return arr[Math.floor(Math.random() * arr.length)];
}

/** Map a tip to its rotation slot; unknown (e.g. rare) tips return null. */
function slotKey(tip) {
  if (tip == null) return null;
  return TEXT_TO_SLOT.has(tip) ? TEXT_TO_SLOT.get(tip) : null;
}

/** Pick a phrasing for the given slot. */
function tipForSlot(slot) {
  if (slot === SUPPORT_SLOT) return randomOf(randomOf(SUPPORT_GROUPS));
  return randomOf(TIP_GROUPS[slot]);
}

/**
 * Pick the next tip: ~2% rare easter-egg, else a phrasing from a random idea
 * slot that differs from the previous tip's slot (no same-idea repeat).
 * @param {string | null} prev - the previously shown tip text
 */
export function pickTip(prev = null) {
  if (Math.random() < RARE_CHANCE) return randomOf(RARE_TIPS);
  const prevSlot = slotKey(prev);
  const pool = prevSlot != null
    ? SLOT_KEYS.filter(s => s !== prevSlot)
    : SLOT_KEYS;
  const choices = pool.length ? pool : SLOT_KEYS;
  return tipForSlot(randomOf(choices));
}

export function stopBootTipRotation() {
  if (_tipTimer) clearInterval(_tipTimer);
  if (_tipFadeTimer) clearTimeout(_tipFadeTimer);
  _tipTimer = null;
  _tipFadeTimer = null;
  const el = document.getElementById("bootLoadingTip");
  if (el) el.classList.remove("is-fading");
}

function showTip(el, text) {
  if (!el) return;
  el.textContent = text;
  _currentTip = text;
}

function advanceTip(el) {
  if (!el || !bootCurtainActive()) {
    stopBootTipRotation();
    return;
  }
  el.classList.add("is-fading");
  if (_tipFadeTimer) clearTimeout(_tipFadeTimer);
  _tipFadeTimer = setTimeout(() => {
    if (!bootCurtainActive()) {
      stopBootTipRotation();
      return;
    }
    const next = pickTip(_currentTip);
    showTip(el, next);
    el.classList.remove("is-fading");
  }, TIP_FADE_MS);
}

/**
 * Show a random tip on the boot curtain and rotate while loading.
 * @param {HTMLElement | null} el - #bootLoadingTip
 */
export function startBootTipRotation(el) {
  stopBootTipRotation();
  if (!el) return;

  const seeded = el.textContent && el.textContent.trim();
  if (seeded) {
    _currentTip = seeded;
  } else {
    showTip(el, pickTip());
  }

  if (prefersReducedMotion()) return;

  _tipTimer = setInterval(() => {
    if (!bootCurtainActive() || !document.getElementById("bootLoadingTip")) {
      stopBootTipRotation();
      return;
    }
    advanceTip(el);
  }, TIP_INTERVAL_MS);
}
