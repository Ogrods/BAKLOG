export const TABLE_ROW_HEIGHT = 56;
export const VIRTUAL_OVERSCAN = 10;
export const VIRTUAL_MIN_ROWS = 80;

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
  const visibleTop = Math.max(rect.top, 0);
  const visibleBottom = Math.min(rect.bottom, window.innerHeight);
  let clientHeight = visibleBottom - visibleTop;
  if (clientHeight <= 0) {
    // Table entirely above or below viewport — still paint a viewport-sized window.
    clientHeight = window.innerHeight;
  }
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

export function virtualRange(scrollTop, viewportHeight, total, rowHeight = TABLE_ROW_HEIGHT, overscan = VIRTUAL_OVERSCAN) {
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
