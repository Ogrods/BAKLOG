/** @deprecated use getTableRowHeight() — kept for importers expecting a number-like export */
export const TABLE_ROW_HEIGHT = 56;
export const VIRTUAL_OVERSCAN = 10;
export const VIRTUAL_MIN_ROWS = 80;

/** Row height from CSS --row-h (changes at responsive breakpoints). */
export function getTableRowHeight() {
  if (typeof document === 'undefined') return 56;
  const raw = getComputedStyle(document.documentElement).getPropertyValue('--row-h').trim();
  const n = parseFloat(raw);
  return Number.isFinite(n) && n > 0 ? n : 56;
}

export function shouldVirtualize(rowCount) {
  return rowCount >= VIRTUAL_MIN_ROWS;
}

/** Metrics for page scroll against a stable anchor (tableShell), not tbody spacers. */
export function tableVirtualMetrics(tableWrapEl) {
  const shell = typeof document !== 'undefined' ? document.getElementById('tableShell') : null;
  const el = shell || tableWrapEl;
  if (!el || typeof window === 'undefined') {
    return { scrollTop: 0, clientHeight: 800 };
  }
  const rect = el.getBoundingClientRect();
  const docTop = rect.top + window.scrollY;
  const thead = tableWrapEl?.querySelector?.('thead');
  const headerH = thead?.offsetHeight ?? 0;
  const scrollTop = Math.max(0, window.scrollY - docTop - headerH);
  // The "viewport" for virtualization is the user's window, not the table's
  // currently-rendered height. Measuring rect.bottom-rect.top would be circular:
  // on the first paint tbody is empty, so the table is only THEAD-tall, which
  // produces a tiny window and paints 1-2 rows. Some webviews (Cursor's embedded
  // browser, certain Electron shells) hit this path; real Chrome usually settles
  // layout before paint and accidentally works. Use window.innerHeight as the
  // floor so we always paint at least a screen of rows.
  const clientHeight = Math.max(window.innerHeight, rect.bottom - Math.max(rect.top, 0));
  return { scrollTop, clientHeight };
}

/** Force the visible slice to include a target row (letter jump, keyboard focus). */
export function virtualRangeAroundIndex(
  anchorIndex,
  total,
  viewportHeight = typeof window !== 'undefined' ? window.innerHeight : 800,
  rowHeight = TABLE_ROW_HEIGHT,
  overscan = VIRTUAL_OVERSCAN,
) {
  if (total <= 0) {
    return { start: 0, end: 0, topPad: 0, bottomPad: 0 };
  }
  const visibleCount = Math.ceil(viewportHeight / rowHeight) + overscan * 2;
  const start = Math.max(0, anchorIndex - overscan);
  const end = Math.min(total, anchorIndex + visibleCount);
  return {
    start,
    end,
    topPad: start * rowHeight,
    bottomPad: Math.max(0, (total - end) * rowHeight),
  };
}

export function virtualRange(scrollTop, viewportHeight, total, rowHeight = getTableRowHeight(), overscan = VIRTUAL_OVERSCAN) {
  if (total <= 0) {
    return { start: 0, end: 0, topPad: 0, bottomPad: 0 };
  }
  const start = Math.max(0, Math.floor(scrollTop / rowHeight) - overscan);
  const end = Math.min(total, Math.ceil((scrollTop + viewportHeight) / rowHeight) + overscan);
  return {
    start,
    end,
    topPad: start * rowHeight,
    bottomPad: Math.max(0, (total - end) * rowHeight),
  };
}
