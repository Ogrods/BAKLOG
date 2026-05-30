export function escapeHtml(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

export function escapeAttr(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
}

export function formatNum(n) {
  const num = Number(n);
  if (!Number.isFinite(num)) return String(n ?? "—");
  return Math.abs(num) >= 10000 ? num.toLocaleString("en-US") : String(num);
}

/** Human-readable calendar date from ISO, YYYY-MM-DD, or already-localized strings. */
export function formatReleaseDate(value) {
  if (value == null || value === "") return "—";
  const s = String(value).trim();
  if (!s) return "—";
  if (/^\d{4}-\d{2}-\d{2}/.test(s)) {
    const t = Date.parse(s.length === 10 ? `${s}T12:00:00` : s);
    if (!Number.isNaN(t)) {
      return new Date(t).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
    }
  }
  const t = Date.parse(s);
  if (!Number.isNaN(t)) {
    return new Date(t).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  }
  return s;
}
