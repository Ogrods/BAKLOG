# FAQ

Straight answers about BAKLOG pricing, privacy, platforms, and getting started.

## Is BAKLOG free?

Yes. Importing your library across every store is free forever: auto-fetch on connect, full dashboard, ownership-aware deals (with sponsored slots in deal cards on the free tier), cached trophy summary % (no on-demand deep re-pull), and **Claimable Now** for full-game giveaways.

Store refresh on the free tier is one store at a time, on demand. Auto-refresh quietly updates one stale store every ~30 min while the app is open.

An optional **$5/mo** paid tier ($50/yr) adds more - see [What's in the paid tier?](#whats-in-the-paid-tier). Nothing you use free today moves behind a paywall.

## What's in the paid tier?

**$5/mo** or **$50/yr** live today:

- No sponsored deal cards
- Scheduled stale-store refresh without keeping the app open
- Deep achievement/trophy sync (full on-demand re-pull; free tier shows cached % only)
- Bonus claimables feed for DLC, add-ons, and in-game bonuses filtered out of the free feed

**Coming soon:** cloud sync across machines, **queued bulk refresh** (queue every stale store back-to-back instead of babysitting one at a time), and deal/watchlist alerts.

See [baklog.app](https://baklog.app/) for checkout links and the full comparison.

## What's the difference between free and paid refresh?

On the free tier, you refresh one store at a time: click a fetcher chip, wait, click the next. Auto-refresh (on by default) quietly updates one stale store every ~30 minutes while the app is open.

Pro adds scheduled refresh that runs even when the app is closed (tray or OS scheduler). Queued bulk refresh (one action queues every stale store) is coming soon. Your credentials and data still stay on your machine.

Details: [Refresh and enrichment](refresh-and-enrichment.md).

## Is it safe?

Your credentials stay encrypted on your machine (OS keyring + AES-GCM fallback). Store fetches use your own browser session and your IP. There is no BAKLOG server holding your logins.

The app is [open source (MIT)](https://github.com/Ogrods/BAKLOG). Read [PRIVACY.md](../PRIVACY.md) and [SECURITY.md](../SECURITY.md) for the full data-handling and threat-model story.

## Do you sell my data?

No. BAKLOG has no business model built on your library. We do not collect, host, or sell personal data - there is no server holding it to sell in the first place.

The marketing site at [baklog.app](https://baklog.app) has a separate waitlist and optional bug-report endpoint - see [PRIVACY.md](../PRIVACY.md#hosted-surfaces).

## Why invite-only right now?

We are onboarding in small waves so we can fix what breaks on real setups before opening the doors. Request access at [baklog.app](https://baklog.app).

## Supported platforms

| OS | Status |
|----|--------|
| **Windows 10/11** | Fully supported (primary development target) |
| **macOS** | Supported with limits - Amazon Games (launcher) and GOG Galaxy (local) are Windows/macOS-only local sources |
| **Linux** | Supported with limits - Amazon Games (launcher) and GOG Galaxy (local) are unavailable; use web Connect instead |

The app itself (dashboard, server, secret storage, browser sign-in) is OS-agnostic. Platform-restricted local providers show as **Unavailable** on unsupported OSes; web fallbacks remain available.

Store-by-store matrix: [Connecting stores](connecting-stores.md#platform-availability).

## I don't own many games yet. Is BAKLOG still for me?

Yes. You don't need a paid library to start. See [baklog.app/#start](https://baklog.app/#start) for free entry paths: Epic, Prime, GOG, free-to-play hits, and more. **Claimable Now** aggregates the week's free drops in your dashboard.

## Does BAKLOG show me free games to claim?

**Claimable Now** is a maintainer-curated free-game feed (Epic, GamerPower, IsThereAnyDeal, and more) in your Wishlist tab. It is ownership-aware: it skips games you already own somewhere in your library. Included on the free tier.

## Why is my count different from what the store shows?

Stores pad your library with things that are not games: DLC skins, soundtracks, wallpapers, betas, and store apps. BAKLOG treats those as **library noise** and auto-hides them so the number you see is real games. Rules live in `js/library-noise.js` (mirrored in Python for fetchers).

Separately, you can hide any game you do not want to see and restore it later from the **Hidden games** panel. See [Using the dashboard](using-the-dashboard.md#library-noise-vs-hidden-list).

## How long does the first import take?

Marketing copy uses ~90 seconds for 0 to 2,000+ games. That number comes from timing a real import on an above-average Steam library. Smaller libraries finish faster; extremely large ones take longer. Each store fetches independently - the fetcher log shows progress.

## Do I have to refresh manually?

Not usually. When you connect a store, BAKLOG auto-fetches its library. While the app is open, auto-refresh for stores older than 24h is on by default (Connections). ITAD deal prices refresh on a schedule.

On the free tier there is no background sync while the app is closed. Pro adds scheduled refresh while closed.

## Isn't scraping against the rules?

BAKLOG automates requests you could make yourself, in your own browser, with your own credentials, on your own machine.

## Is it open source?

Yes. BAKLOG is released under the [MIT license](https://github.com/Ogrods/BAKLOG/blob/main/LICENSE). The full app (server, fetchers, auth, and dashboard) lives in the public GitHub repo. Optional paid features are conveniences on top of the same open codebase, not a fork of your data into our cloud.
