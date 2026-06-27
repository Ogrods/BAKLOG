/** Shared Pro entitlement + mirror path helpers for landing/api/mirror.js */

export const MIRROR_BUCKET = "baklog-mirror";

export const ALLOWED_ARTIFACT =
  /^(games_[a-z0-9_]+\.json|games_wishlist_[a-z0-9_]+\.json|itad_prices\.json|free_claims\.json|data\/personal\.json)$/;

const PRO_ALIASES = new Set(["pro", "paid", "premium"]);

/** Match shared/profile_paths.py _PROFILE_ID_RE (lowercase ids). */
const PROFILE_ID_RE = /^[a-z0-9][a-z0-9-]*$/;

export function pickEnv(...keys) {
  for (const key of keys) {
    const val = process.env[key];
    if (typeof val === "string" && val.trim()) return val.trim();
  }
  return "";
}

export function loadCompProEmails() {
  const raw = pickEnv("BAKLOG_COMP_PRO_EMAILS");
  if (!raw) return new Set();
  return new Set(
    raw
      .split(/[\n,;]+/)
      .map((line) => line.replace(/#.*$/, "").trim().toLowerCase())
      .filter((email) => email.includes("@")),
  );
}

export function extractPlan(user) {
  const meta = user?.app_metadata || {};
  const plan = String(meta.plan || user?.plan || "").trim().toLowerCase();
  return PRO_ALIASES.has(plan);
}

export function isCompProEmail(email, compEmails = loadCompProEmails()) {
  const normalized = String(email || "").trim().toLowerCase();
  return normalized !== "" && compEmails.has(normalized);
}

/** True when JWT plan is Pro or email is on BAKLOG_COMP_PRO_EMAILS (Vercel env). */
export function isProUser(user) {
  if (!user || typeof user !== "object") return false;
  if (extractPlan(user)) return true;
  return isCompProEmail(user.email);
}

export function isValidProfileId(profileId) {
  const pid = String(profileId || "").trim();
  if (!pid || pid === "." || pid === "..") return false;
  if (pid.includes("/") || pid.includes("\\")) return false;
  return PROFILE_ID_RE.test(pid);
}

export function normalizeProfileId(profileId) {
  const pid = String(profileId || "").trim();
  if (!isValidProfileId(pid)) {
    throw new Error("invalid profile id");
  }
  return pid;
}

export function storageBase(supabaseUrl) {
  return `${supabaseUrl.replace(/\/$/, "")}/storage/v1/object`;
}

export function encodeObjectKey(key) {
  return key.split("/").map(encodeURIComponent).join("/");
}

/** Parse list rows under ``{userId}/`` into mirror artifacts with profile ids. */
export function parseMirrorListRows(rows, userId) {
  const uid = String(userId || "").trim();
  const artifacts = [];
  const profiles = new Set();

  for (const row of rows || []) {
    if (!row || !row.name) continue;
    const name = String(row.name).trim().replace(/^\/+/, "");
    if (!name || name.endsWith("/")) continue;

    let profileId = "";
    let artifactPath = name;

    if (name.includes("/")) {
      const slash = name.indexOf("/");
      profileId = name.slice(0, slash);
      artifactPath = name.slice(slash + 1);
    } else {
      continue;
    }

    if (!isValidProfileId(profileId)) continue;
    if (!ALLOWED_ARTIFACT.test(artifactPath)) continue;

    profiles.add(profileId);
    artifacts.push({
      path: artifactPath,
      profile: profileId,
      id: row.id,
      updated_at: row.updated_at,
      metadata: row.metadata,
    });
  }

  artifacts.sort(
    (a, b) =>
      (a.profile || "").localeCompare(b.profile || "") ||
      (a.path || "").localeCompare(b.path || ""),
  );

  return {
    artifacts,
    profiles: [...profiles].sort((a, b) => a.localeCompare(b)),
  };
}

/** Pick profile for a download when the client omits ``?profile=``. */
export function resolveArtifactProfile(artifacts, artifactPath, userId) {
  const matches = (artifacts || []).filter((row) => row.path === artifactPath);
  if (!matches.length) return null;
  const prefs = [String(userId || "").trim(), "default"];
  for (const pref of prefs) {
    const hit = matches.find((row) => row.profile === pref);
    if (hit) return hit.profile;
  }
  return matches[0].profile;
}
