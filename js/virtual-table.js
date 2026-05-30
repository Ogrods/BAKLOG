export const TABLE_ROW_HEIGHT = 56;
export const VIRTUAL_OVERSCAN = 10;
export const VIRTUAL_MIN_ROWS = 80;

export function shouldVirtualize(rowCount) {
  return rowCount >= VIRTUAL_MIN_ROWS;
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
