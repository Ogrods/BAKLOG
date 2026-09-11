/** Pure virtual-window math for hosted /mirror (no DOM). */

export const MIRROR_VIRTUAL_THRESHOLD = 60;
export const MIRROR_VIRTUAL_OVERSCAN = 12;
export const MIRROR_ROW_HEIGHT_DESKTOP = 72;
export const MIRROR_ROW_HEIGHT_PHONE = 220;

/**
 * @param {number} listLen
 * @param {{ scrollY: number, viewportH: number, rowHeight: number, tableTop: number, overscan?: number }} opts
 * @returns {{ start: number, end: number }}
 */
export function computeMirrorVirtualRange(listLen, opts) {
  const len = Math.max(0, Math.floor(Number(listLen) || 0));
  if (len <= 0) return { start: 0, end: 0 };
  const rh = Math.max(1, Number(opts.rowHeight) || MIRROR_ROW_HEIGHT_DESKTOP);
  const overscan = Number.isFinite(opts.overscan) ? opts.overscan : MIRROR_VIRTUAL_OVERSCAN;
  const scrollY = Math.max(0, Number(opts.scrollY) || 0);
  const viewportH = Math.max(1, Number(opts.viewportH) || 1);
  const tableTop = Number(opts.tableTop) || 0;

  let start = Math.max(0, Math.floor((scrollY - tableTop) / rh) - overscan);
  let end = Math.min(len, Math.ceil((scrollY + viewportH - tableTop) / rh) + overscan);
  if (end <= start) {
    end = Math.min(len, start + Math.ceil(viewportH / rh) + overscan * 2);
  }
  if (start >= len) {
    const windowRows = Math.ceil(viewportH / rh) + overscan * 2;
    start = Math.max(0, len - windowRows);
    end = len;
  }
  start = Math.max(0, Math.min(start, len));
  end = Math.max(start, Math.min(end, len));
  return { start, end };
}

export function usesMirrorVirtualScroll(listLen, threshold = MIRROR_VIRTUAL_THRESHOLD) {
  return (Number(listLen) || 0) > threshold;
}
