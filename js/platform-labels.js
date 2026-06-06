/** Map sys.platform ids to user-facing OS names for Connections / fetcher chips. */

const PLATFORM_LABELS = {
  win32: 'Windows',
  darwin: 'macOS',
  linux: 'Linux',
};

export function formatPlatformLabel(platform) {
  const key = String(platform || '').trim();
  return PLATFORM_LABELS[key] || key || 'Windows';
}

/** Join provider/fetcher platform restrictions for tooltips and unavailable copy. */
export function formatPlatformList(platforms) {
  const list = Array.isArray(platforms) ? platforms.filter(Boolean) : [];
  if (!list.length) return 'Windows';
  return list.map(formatPlatformLabel).join(', ');
}
