/**
 * Canonical baklog:* custom events — names, dispatch targets, and consumers.
 * Emitters should import these constants; tests assert parity with this table.
 */

export const BAKLOG_AUTH_STATUS = 'baklog:auth-status';
export const BAKLOG_RECONNECT_DISMISS = 'baklog:reconnect-dismiss';
export const BAKLOG_DEEP_SYNC = 'baklog:deep-sync';
export const BAKLOG_THEME_CHANGE = 'baklog:themechange';
export const BAKLOG_OPEN_BUG_REPORT = 'baklog:open-bug-report';

/** @typedef {{ name: string, target: 'document' | 'window', emitters: string[], listeners: string[] }} BaklogEventSpec */

/** @type {Record<string, BaklogEventSpec>} */
export const BAKLOG_EVENT_REGISTRY = {
  [BAKLOG_AUTH_STATUS]: {
    name: BAKLOG_AUTH_STATUS,
    target: 'document',
    emitters: ['js/connections.js'],
    listeners: ['js/fetcher-health.js', 'js/connections.js'],
  },
  [BAKLOG_RECONNECT_DISMISS]: {
    name: BAKLOG_RECONNECT_DISMISS,
    target: 'document',
    emitters: ['js/connections.js'],
    listeners: ['js/fetcher-health.js'],
  },
  [BAKLOG_DEEP_SYNC]: {
    name: BAKLOG_DEEP_SYNC,
    target: 'document',
    emitters: ['js/trophy-popover.js'],
    listeners: ['js/bind-events-fetcher.js'],
  },
  [BAKLOG_THEME_CHANGE]: {
    name: BAKLOG_THEME_CHANGE,
    target: 'window',
    emitters: ['js/theme.js'],
    listeners: ['js/dashboard.js'],
  },
  [BAKLOG_OPEN_BUG_REPORT]: {
    name: BAKLOG_OPEN_BUG_REPORT,
    target: 'window',
    emitters: ['js/error-boundary.js'],
    listeners: ['js/bug-report.js'],
  },
};
