/**
 * Mutable facade so table-ui can call library-load without a static import cycle.
 * library-load.js registers the real refreshAfterManualChange at module init.
 */

export const libraryLoadApi = {
  refreshAfterManualChange() {},
};

/** @param {{ refreshAfterManualChange?: () => void }} partial */
export function registerLibraryLoadApi(partial) {
  if (!partial || typeof partial !== "object") return;
  Object.assign(libraryLoadApi, partial);
}
