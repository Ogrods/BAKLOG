# Architecture decision records

Short public "why" notes for BAKLOG. Deep maintainer notes stay in the private
`baklog-internal` clone; this index is for contributors and reviewers.

| ADR | Title |
|-----|-------|
| [001](001-local-first-stdlib-http.md) | Local-first stdlib HTTP + browser-tab UI |
| [002](002-whitelisted-subprocess-fetchers.md) | Whitelisted subprocess fetchers via manifest |
| [003](003-fetcher-exit-codes.md) | Fetcher exit codes and refuse-empty/drift |
| [004](004-cdp-aes-gcm-secrets.md) | CDP sign-in + AES-GCM secrets + OS keyring |
| [005](005-layered-localhost-auth.md) | Layered localhost authorization |
| [006](006-pro-mirror-allowlist.md) | Opt-in Pro mirror allowlist only |
| [007](007-sync-pairs-in-ci.md) | Cross-language sync pairs enforced in CI |
| [008](008-no-silent-updates.md) | No silent background app updates |

Start with [`ARCHITECTURE.md`](../../ARCHITECTURE.md) and [`FOR_REVIEWERS.md`](../../FOR_REVIEWERS.md).
