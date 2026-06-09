export function escapeHtml(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

export function escapeAttr(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
}

export function formatNum(n) {
  const num = Number(n);
  if (!Number.isFinite(num)) return String(n ?? " - ");
  return Math.abs(num) >= 10000 ? num.toLocaleString("en-US") : String(num);
}

/**
 * True only for absolute http/https URLs. Rejects javascript:/data: schemes,
 * protocol-relative ("//host"), and relative/invalid strings — the guard for
 * any URL that comes from a feed (claim links, sponsor links, cover images)
 * before it reaches an href, src, or window.open().
 */
export function isSafeHttpUrl(url) {
  if (typeof url !== "string" || !url.trim()) return false;
  try {
    const u = new URL(url.trim());
    return u.protocol === "http:" || u.protocol === "https:";
  } catch {
    return false;
  }
}

/**
 * Native `title` tooltips only resolve to the nearest ancestor that has a
 * `title`, so a checkbox's tooltip never shows when hovering the sibling label
 * text. Copy each checkbox's `title` onto its wrapping <label> (when the label
 * has no title of its own) so hovering anywhere on the label — text included —
 * surfaces the same tooltip. Safe to re-run; skips labels that already have a
 * title. Pass a subtree `root` to cover dynamically rendered checkboxes.
 */
export function syncCheckboxLabelTitles(root = document) {
  if (!root || typeof root.querySelectorAll !== "function") return;
  root.querySelectorAll('input[type="checkbox"][title]').forEach(box => {
    const label = box.closest("label");
    if (label && !label.getAttribute("title")) {
      label.setAttribute("title", box.getAttribute("title"));
    }
  });
}
