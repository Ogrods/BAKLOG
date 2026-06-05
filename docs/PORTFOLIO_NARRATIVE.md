# BAKLOG — Founding / Full-Stack Engineer Portfolio Narrative

**Author:** Dan Ogonoski  
**Date:** 2026-06-04  
**Purpose:** Reusable story for job applications, interviews, and portfolio sites.  
**Repo:** https://github.com/Ogrods/steam-backlog

> **Accuracy disclaimer:** BAKLOG is a solo-built product in pre-launch / soft-launch shape. Lead with **engineering breadth, ownership, and production discipline** — not user counts or revenue (there are none yet). Do not overstate traction. For business gaps before scale, see [STRATEGY_AUDIT.md](STRATEGY_AUDIT.md).

---

## Positioning line (one sentence)

**Solo-built a production-grade, local-first platform that aggregates 20 storefront libraries on the user's machine — spanning Python backend, CDP browser automation, encrypted credential storage, vanilla-JS SPA with virtualized tables, and a documented security/privacy threat model — with CI, 480 tests, and founder-level product/IP strategy.**

Use this as the opening line on LinkedIn, cover letters, or "tell me about a project you're proud of."

---

## What it proves (capability matrix)

| Dimension | What BAKLOG demonstrates | Where to point reviewers |
|-----------|--------------------------|-------------------------|
| **Full-stack breadth** | HTTP server, subprocess orchestration, SSE streaming, SPA routing, CSS design system, build/test pipeline | [server.py](../server.py), [js/](../js/), [app.css](../app.css), [package.json](../package.json) |
| **Hard integration problems** | Session-replay auth across 12 library + 8 wishlist sources via CDP, bearer sniffing, OAuth, local DB reads | [auth/runner.py](../auth/runner.py), [auth/cdp_browser.py](../auth/cdp_browser.py), [fetchers/manifest.json](../fetchers/manifest.json) |
| **Security / privacy** | AES-256-GCM secrets, OS keyring, 127.0.0.1-only server, CSRF guard, whitelist fetchers, redacted logs | [auth/secrets.py](../auth/secrets.py), [SECURITY.md](../SECURITY.md), [PRIVACY.md](../PRIVACY.md) |
| **Data integrity** | Atomic writes, drift guard, merge-on-refetch preserving enrichment fields | [fetchers/_base.py](../fetchers/_base.py), [shared/json_util.py](../shared/json_util.py) |
| **Frontend at scale** | Virtual scrolling, Web Worker filter/sort, progressive table paint | [js/table-ui.js](../js/table-ui.js), [js/table-query.worker.js](../js/table-query.worker.js) |
| **Domain logic** | Cross-store dedupe, ownership-aware deal suppression, FX normalization | [js/game-core.js](../js/game-core.js), [js/deals.js](../js/deals.js), [shared/wishlist_fx.py](../shared/wishlist_fx.py) |
| **Production discipline** | pytest + vitest (480 tests), GitHub Actions, axe-core, Lighthouse a11y/SEO/BP at 100 | [.github/workflows/](../.github/workflows/), [tests/](../tests/) |
| **Founder-level ownership** | Monetization modeling, GTM, defensive publication, legal strategy memo | [tracker.html](../tracker.html), [docs/LEGAL_STRATEGY.md](LEGAL_STRATEGY.md), [docs/DEFENSIVE_PUBLICATION.md](DEFENSIVE_PUBLICATION.md) |

---

## Resume / LinkedIn bullets (copy-paste)

Adapt numbers if the test count changes; keep claims verifiable.

1. **Architected and shipped a local-first game library platform** integrating 20 storefront APIs (Steam, Epic, GOG, PSN, Xbox, Nintendo, EA, etc.) with no central credential server — credentials encrypted per-profile (AES-256-GCM + OS keyring).

2. **Built a CDP-driven browser authentication layer** (Chrome DevTools Protocol) capturing cookies, OAuth codes, and Bearer tokens from user sign-in sessions for replay against storefront web APIs on the user's machine.

3. **Implemented cross-store identity reconciliation** (normalized-title dedupe, store-priority survivor selection, combined playtime rollup) and ownership-aware wishlist deal filtering fused with IsThereAnyDeal pricing.

4. **Delivered production hardening:** atomic JSON writes, fetcher drift guard preventing empty catalog overwrites, localhost CSRF protection, subprocess timeout job objects, durable fetcher queue with SSE log streaming.

5. **Owned full stack:** Python HTTP server + whitelisted fetcher subprocesses, vanilla-JS dashboard (virtual scroll, Web Worker queries), 5k+ lines CSS, pytest/vitest suite (**480 tests**), CI on Windows.

6. **Documented threat model and privacy posture** (zero telemetry, 127.0.0.1 bind, whitelist bug bundles) and authored defensive publication establishing prior art for the aggregation mechanism.

7. **Drove product strategy:** monetization thesis, go-to-market sequencing, licensing outreach framework, and IP/legal guardrails — not just implementation.

---

## Interview talking points (STAR format)

Use these when asked about hard problems, ownership, or tradeoffs.

### Story 1: Fetcher refetch was wiping enrichment data

- **Situation:** Non-Steam fetchers rebuilt rows from store APIs on every refresh, overwriting Steam review scores and HLTB hours that came from separate enrichers — silent data loss across the library.
- **Task:** Stop refetch from destroying enrichment without blocking fresh store-owned fields.
- **Action:** Introduced `merge_cached_row()` in `fetchers/_base.py` with per-store **authoritative field sets** in `fetchers/_authoritative.py` — store owns IDs and playtime; enrichers own reviews and HLTB unless explicitly refreshed.
- **Result:** Refetch preserves enrichment; drift guard still catches catastrophic empty writes. Documented in tracker `find_fetcher_review_wipe`.

### Story 2: PSN cross-gen playtime and broken store URLs

- **Situation:** PSN dedupe merged trophy-only rows with entitlement rows but kept stale psnprofiles URLs; Fortnite playtime split across PS4/PS5 rows undercounted total time.
- **Task:** Fix dedupe merge logic and URL generation without breaking existing on-disk data.
- **Action:** Rebuild `store_url` from merged `concept_id` after dedupe; sum `title_stats` playtime by dedupe key in `psn_client.py`; add dedicated PSN branch in `storeUrlForGame()` preferring concept URLs.
- **Result:** Correct links and combined playtime on survivor rows. Tracker: `find_psn_url_dedupe_drift`, `p3_psn_crossgen_playtime`.

### Story 3: Drift guard — empty fetch must not clobber library

- **Situation:** Auth expiry or API changes could write empty or tiny JSON files over a user's 2,000-game library.
- **Task:** Fail safe on suspicious row-count drops.
- **Action:** `refuse_drift_result` in fetcher base — compare fresh vs cached counts; exit non-zero on catastrophic shrink; surface honest reconnect chips in UI.
- **Result:** Zero silent library wipes post-ship. Tracker: `bs_data_drift`.

### Story 4: Privacy vs observability tradeoff

- **Situation:** Need to debug user issues without becoming a data company.
- **Task:** Support bug reports without telemetry.
- **Action:** Whitelist-only local bug bundle (`buildBugBundle()`), rolling error log in localStorage, opt-in copy from toast — no network send by default.
- **Result:** Support workflow exists; privacy promise intact. Tracker: `bs_telemetry`, [PRIVACY.md](../PRIVACY.md).

---

## Gaps to fix before using as flagship artifact

An interviewer or hiring manager may clone and run the repo. Address these first (see [STRATEGY_AUDIT.md](STRATEGY_AUDIT.md)):

| Gap | Why it matters for job search | Action |
|-----|------------------------------|--------|
| **Live demo unreliable** | "Run it live" in interview fails | Fix Steam connect + fetch path first |
| **Install friction** | Reviewer abandons at Python setup | Ship PyInstaller/installer or clear 3-step verified README |
| **No 60s video** | Busy reviewers won't clone | Record magic-moment screen capture |
| **No case study page** | GitHub alone is dense | 1-page "problem → architecture → highlights" on portfolio site |
| **No metrics story** | Can't claim traction | Be honest: "pre-launch"; lead with test count, integration breadth, hardening |

---

## How to deploy this artifact

### GitHub

- Pin the repo on your profile.
- README hero: screenshot + 30s pitch + verified install steps (`p4_readme_rewrite`).
- Link to this doc or a trimmed `docs/` index for reviewers who want depth.

### Portfolio site / case study

Suggested sections (1–2 pages):

1. **Problem** — accidental libraries across five launchers; no ownership-aware deals.
2. **Architecture diagram** — local server, CDP auth, fetchers, browser UI (reuse mermaid from [DEFENSIVE_PUBLICATION.md](DEFENSIVE_PUBLICATION.md)).
3. **Highlights** — 3 bullets from capability matrix above.
4. **Hard problem** — one STAR story (Story 1 or 3).
5. **Stack + scale** — 480 tests, 20 integrations, zero telemetry.
6. **Links** — repo, SECURITY.md, optional demo video.

### Cover letter / application

- Open with the **positioning line**.
- Pick **2 resume bullets** matched to the job description (security role → bullets 2+4; full-stack → 1+5; product-minded eng → 7+3).
- Offer: *"Happy to walk through architecture or run a live demo."* (Only if demo is fixed.)

### Roles this narrative fits best

| Role | Emphasize |
|------|-----------|
| **Founding / full-stack engineer** | Entire matrix — breadth + ownership + strategy |
| **Backend / platform engineer** | server.py, fetchers, auth, subprocess guard, atomic IO |
| **Security-minded engineer** | SECURITY.md, secrets, CSRF, local-first, threat model |
| **Product engineer** | Dedupe, deals, onboarding, monetization thesis |

Less ideal fit (unless you reposition): pure mobile, pure ML, roles requiring shipped consumer scale metrics you do not have yet.

---

## What not to claim

- User counts, MAU, MRR, or "thousands of users" — **not true yet**.
- "Patented" or "patent pending" — **not filed**; defensive publication only.
- Store partnership or endorsement — **not affiliated** with Steam, Epic, etc.
- "Fully working across all 20 stores" — **AUDIT_FINDINGS** notes fetcher drift; be honest about demo-critical vs best-effort.

Lead with **what you built, how you built it, and how you think** — that is the founding-engineer story this repo tells.

---

## Related documents

| Document | Use |
|----------|-----|
| [STRATEGY_AUDIT.md](STRATEGY_AUDIT.md) | Business gaps, scale path, honest outcomes |
| [LEGAL_STRATEGY.md](LEGAL_STRATEGY.md) | IP, licensing, guardrails |
| [DEFENSIVE_PUBLICATION.md](DEFENSIVE_PUBLICATION.md) | Technical mechanism depth |
| [SECURITY.md](../SECURITY.md) | Threat model for security interviews |
| [AUDIT_FINDINGS.md](AUDIT_FINDINGS.md) | Production audit evidence |

**Last updated:** 2026-06-04
