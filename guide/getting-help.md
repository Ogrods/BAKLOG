# Getting help

Report bugs, ask questions, or join the community.

## Report a bug from the app

When something goes wrong, BAKLOG captures uncaught errors and unhandled promise rejections automatically and surfaces a sticky red toast in the top-right corner. From the toast, kebab menu (**Report a bug…**), or `?debug=1` overlay you can:

- **Send report** - opens a consent dialog showing the exact sanitized JSON payload (errors + app context: version, view, data version, filter count, table fingerprint, last render time, dashboard counters). Add an optional contact email and note, then confirm to POST the bundle to the maintainer. Nothing is sent until you click **Send report**. Personal notes, library JSON, and credentials are never included (see [PRIVACY.md](../PRIVACY.md#error-logs-and-bug-reporting)).
- **Copy bug bundle** - same payload to your clipboard with no network request. Paste into a [new GitHub issue](https://github.com/Ogrods/BAKLOG/issues/new) if you prefer.
- **Errors only** - copies just the error array, without app context.
- **Details** - expand the stack trace inline.

The last 200 errors are kept in browser `localStorage`. Clear the ring with `localStorage.removeItem('baklog-error-log')` in DevTools.

**Fetcher failures are separate.** Store refresh problems show up in the Fetcher health panel and `profiles/<id>/cache/runs/*.jsonl` logs (exit codes 0-4). They are not auto-sent to the bug-report endpoint. See [Troubleshooting](troubleshooting.md).

**Quick test:** DevTools → `throw new Error('test')` → sticky toast appears → **Report a bug…** shows the scrubbed bundle preview. Nothing is POSTed until you click **Send report**.

For local dev without hitting production, set `window.__BAKLOG_REPORT_ENDPOINT` or the `baklog-report-endpoint` meta tag in `index.html` (see [PRIVACY.md](../PRIVACY.md#error-logs-and-bug-reporting)).

## Community and support

| Channel | Link | Best for |
|---------|------|----------|
| **Discord** | [discord.gg/VFvxN5nCCB](https://discord.gg/VFvxN5nCCB) | Beta chat, `#bug-reports`, `#feature-requests` |
| **GitHub** | [github.com/Ogrods/BAKLOG](https://github.com/Ogrods/BAKLOG) | Source code (MIT), reproducible bugs, feature requests |
| **GitHub Issues** | [New issue](https://github.com/Ogrods/BAKLOG/issues/new) | Long-term bug and feature record |
| **Email** | [dan@baklog.app](mailto:dan@baklog.app) | Invite or support questions |

No app data is piped to Discord. Use **Report a bug…** or paste a **Copy bug bundle** when filing bugs there.

Discord invite and GitHub repo URLs are canonical in [`shared/community.json`](../shared/community.json).

## Before you ask

1. [Troubleshooting](troubleshooting.md) - auth failures, 403s, empty results, platform limits
2. [Connecting stores](connecting-stores.md) - per-store privacy settings and CLI fallbacks
3. [FAQ](faq.md) - free vs paid, invite-only access, count differences

## Full user guide

Browse the rest of the guide from [guide/README.md](README.md).
