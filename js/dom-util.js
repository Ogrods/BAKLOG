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
