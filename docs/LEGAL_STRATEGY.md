# BAKLOG — Legal & IP Strategy

**Owner:** Dan Ogrodnik  
**Last updated:** 2026-06-04  
**Status:** Working strategy memo — consolidates IP posture, licensing goals, and self-protection guardrails.

> **This is not legal advice.** This memo is an internal plan to avoid foot-guns and to brief an attorney efficiently. Before any patent filing, trademark registration, or signed license/commercial agreement, have a qualified attorney review. Companion docs: [IP.md](../IP.md), [DEFENSIVE_PUBLICATION.md](DEFENSIVE_PUBLICATION.md), [LICENSE](../LICENSE), [PRIVACY.md](../PRIVACY.md), [SECURITY.md](../SECURITY.md).

---

## 1. TL;DR — where we stand

- **The code is open source (MIT) and already public** on GitHub since **2026-05-27**. That is a deliberate, irreversible-for-released-versions choice.
- **We are not relying on patents.** A defensive publication ([DEFENSIVE_PUBLICATION.md](DEFENSIVE_PUBLICATION.md)) establishes prior art so *no one else* can patent the core mechanism and block us.
- **The real assets are: the brand (BAKLOG name + logo), execution speed, trust/positioning, and any future non-MIT code or hosted service.** Those — not the published code — are what we license or sell.
- **The real legal *risk* is storefront Terms-of-Service**, not IP. The product replays the user's own store sessions. We have positioned this carefully and must keep doing so.
- **Goal of current outreach:** get a one-pager to decision-makers (marketing/product/CEO) and advance to a **license-agreement negotiation** — see Monetization → Go-to-market in `tracker.html`.

---

## 2. What we own and how it's protected

| Asset | Protection | Notes |
|-------|-----------|-------|
| Source code, UI, copy | **Copyright** (auto) + **MIT license** | MIT lets others use/modify/redistribute the code with attribution. We keep copyright. |
| **BAKLOG** name + brick-stack logo | **Trademark** (currently unregistered/common-law) | This is the most licensable asset. Registration is recommended (see §5). |
| Marketing assets (logos under `assets/`, `marketing/assets/logo/`) | Copyright + trademark | Treated as brand assets, not clip art. |
| The aggregation *mechanism* (session replay, dedupe, ownership-aware deals) | **Defensive publication** (prior art) | We chose to publish, not patent. Prevents others from patenting it. |
| Hosted service / future private modules | Trade secret + separate license (if built) | Anything we never publish under MIT can be commercially licensed. |

**Key mental model:** Copyright protects *expression* (our code). Trademark protects *brand confusion* (our name/logo). Patents are optional monopolies on *inventions*. **You do not need a patent to sell or license software.**

---

## 3. The MIT "one-way door" — read before any license deal

This is the single most important thing to not get wrong in negotiations:

- **MIT is irrevocable for versions already released.** We cannot "un-open-source" code that's already on the public repo. Anyone who has it can keep using it under MIT forever.
- **We can still:** change the license on *future* versions, dual-license, keep new modules private, and license the **brand / hosted product / support / partnership**.
- **Therefore, in a license negotiation we must NOT promise:**
  - Exclusive rights to the already-published MIT code (we can't deliver that).
  - That a partner is the "only" party who can run the open-source code (they aren't).
- **What we CAN license / sell to a partner:**
  - The **BAKLOG trademark** and official-product status.
  - A **hosted / managed** version or cloud sync (if/when built).
  - **Support, SLAs, integration work, co-marketing.**
  - **Future proprietary features** developed outside the MIT tree.
  - A **commercial license / exception** for partners who don't want MIT's terms (e.g., want to ship closed-source derivatives under their brand).

> Practical takeaway: position deals as **"open core + commercial license"**, not "buy our secret software."

---

## 4. Patent posture (decided: publish, don't file)

- **Decision:** Defensive publication, not a patent. Rationale: crowded prior art (Playnite, MyGamesAnywhere, Vaulted, ITAD, gmfind), §101 abstract-idea risk, cost, and our open-source brand.
- **Clock facts (US, first-inventor-to-file):**
  - First public disclosure: **2026-05-27** (public repo).
  - **US grace period:** a provisional could still be filed up to ~**2027-05-27**. After that, our own repo is prior art against us and bars a US patent.
  - **Foreign (EU, CN, JP, most):** absolute novelty — public repo since 2026-05-27 has **likely already forfeited** these rights. Do not assume otherwise or promise foreign patent coverage to anyone.
- **Don't-do-anything-stupid rules:**
  - **Don't claim "patent pending"** anywhere (marketing, one-pager, deck) — it's false until/unless a provisional is actually filed. False marking has penalties.
  - **Don't tell a partner we have or will get patents** unless we've filed and counsel confirms scope.
  - If a partner *requires* patent protection as deal value, that's a flag to talk to a patent attorney **before** 2027-05-27 — and to understand foreign rights are probably gone.

---

## 5. Trademark — the asset worth securing

Because the licensing goal centers on the **BAKLOG brand**, the trademark matters more than any patent.

- **Now:** likely common-law rights from use in commerce. Weak and geographically limited.
- **Recommended:** consult an attorney about a **USPTO trademark registration** for the BAKLOG word mark (and possibly the logo). This is the asset a licensee actually pays to use.
- **Risks to avoid:**
  - **Someone else registering "BAKLOG" first** — registration is roughly first-to-file/use; squatters happen once there's buzz. Don't broadcast widely before deciding on filing.
  - **Genericizing the mark** — always use BAKLOG as a brand adjective, not a generic verb/noun in our own copy.
  - **Clearance:** confirm "BAKLOG" doesn't infringe an existing mark before spending on registration or a big launch.
- **Third-party marks:** Steam, Epic, GOG, PlayStation, Xbox, itch.io, IsThereAnyDeal, etc. are owned by others. Keep the existing disclaimer (we are not affiliated/endorsed) and **never** imply partnership we don't have.

---

## 6. The biggest actual risk: storefront Terms of Service

This is where we could genuinely hurt ourselves, and it's **not** an IP issue.

- **What we do:** replay the *user's own* authenticated session against the *same* endpoints the store's website uses, from the *user's* machine and IP. Framed as "automation of your own access," not third-party scraping.
- **Guardrails already in place (keep them, do not regress):**
  - **Never centralize or pool credentials.** No shared server, no proxying fetches for other users.
  - **Never ship stolen/first-party client secrets** (e.g., EA uses web-session replay, *not* desktop-client impersonation with baked-in secrets).
  - **User-initiated, reasonable rate, own account only.** No CAPTCHA-solving, no mass automation.
  - **Don't host or redistribute fetched catalogs** or aggregate ownership datasets.
  - **Copy precision:** "automates what *you* could do in your browser on *your* machine" — never "we aggregate store data."
- **Honest disclosure to keep:** SECURITY.md states this runs **at the user's own risk** under each store's terms. Keep that. A store could still send a cease-and-desist or block an endpoint regardless of our framing.
- **Don't-do-anything-stupid rules:**
  - **Don't market BAKLOG as endorsed/partnered** with any store.
  - **Don't add features that clearly cross into ToS abuse** (auto-purchasing at scale, account sharing, credential pooling, reselling pulled data).
  - If we ever build a **hosted** version that fetches server-side, the ToS calculus changes completely — get counsel first. The local-first architecture is also a legal shield.

---

## 7. Privacy / data-protection posture (a strength — keep it)

- **Local-first, no server, no telemetry** → we collect nothing, so GDPR/CCPA exposure is minimal by design. This is documented in [PRIVACY.md](../PRIVACY.md).
- Credentials are encrypted locally (AES-256-GCM + OS keyring). See [SECURITY.md](../SECURITY.md).
- **Don't-do-anything-stupid rules:**
  - **Don't add silent telemetry or analytics.** The zero-telemetry promise is product truth and a legal asset; breaking it creates disclosure obligations and destroys the trust narrative.
  - **Don't default-on any cloud sync.** If cloud is ever added, it must be opt-in with clear disclosure, or it kills the privacy thesis (and adds GDPR/CCPA duties).
  - If we ever collect emails (waitlist), that small dataset *does* trigger basic privacy duties — handle it properly.

---

## 8. Contributor & dependency hygiene (protects the ability to license)

- **Contributor IP:** if outside contributors submit PRs, their copyright isn't automatically ours. To keep clean rights for dual-licensing/commercial deals, consider a lightweight **CLA or DCO** before accepting significant external contributions. Otherwise we may be unable to relicense parts of the code.
- **Dependencies:** keep an eye on the licenses of libraries we bundle. **Avoid copyleft (GPL/AGPL) deps** that would force us to open-source more than we intend or complicate a commercial license. MIT/BSD/Apache-2.0 deps are safe.
- **Third-party assets:** fonts, icons, images must have licenses compatible with commercial redistribution. No random web clip art in shipped/marketed assets.

---

## 9. Marketing & outreach guardrails

- **No false "patent pending" / "patented."**
- **Affiliate disclosure (FTC):** if/when deal cards use affiliate links or sponsored slots, disclose on every slot. This is already in the monetization plan — keep it.
- **Comparative claims:** comparisons to Playnite, ITAD, Vaulted, GG, etc. must be factual; don't disparage or misstate competitors.
- **Ownership language:** be careful with "own" — digital storefronts grant licenses, not ownership (cf. California AB 2426). Our copy can say "what you've claimed/acquired/have access to" to stay accurate.
- **Outreach to companies (current play):** sending a one-pager and seeking a licensing conversation is fine. **Don't** share anything confidential and don't imply we have rights we don't (patents, store partnerships).
- **Attorney usage for the licensing deal:**
  - **Run the negotiations ourselves.** Engage a lawyer at **contract time** — when terms are ready to paper — not during the back-and-forth. Negotiation rounds are normal (see Monetization → Go-to-market in `tracker.html`) and don't each need legal spend.
  - **Use a licensing / commercial-contracts attorney, NOT a patent attorney,** for the agreement. Patents are a separate track and irrelevant to papering this license.
  - **Find a confidant** experienced with licensing deals to use as an informal sounding board during negotiations — sanity-check terms and tactics. This is an advisor/mentor relationship, not a hired attorney, and complements (doesn't replace) the contract-time legal review.

---

## 10. Action checklist

| Priority | Action | Why |
|----------|--------|-----|
| High | Decide on **trademark registration** for BAKLOG (clearance search + USPTO filing) | The brand is the licensable asset |
| High | Keep all **ToS guardrails** in §6 intact; review before any new fetch/automation feature | This is our real exposure |
| High | In any license talk, frame as **open core + brand/commercial license**; never promise exclusivity over MIT code | Avoid undeliverable promises |
| Medium | Add a **CLA/DCO** if external contributions grow | Preserve clean rights for licensing |
| Medium | Decide before **~2027-05-27** whether a US provisional is worth filing (probably not, but it's the deadline) | Don't lose the option by accident |
| Medium | Audit **dependency licenses**; avoid GPL/AGPL | Keep commercial licensing clean |
| Low | Scrub marketing for accidental **"patent pending"** or **store-endorsement** implications | Avoid false claims |
| Ongoing | Engage a **licensing / commercial-contracts attorney at contract time** (not during negotiations; not a patent attorney) | Negotiate ourselves; pay for legal review when papering terms |

---

## 11. What we are explicitly NOT doing (and why that's fine)

- **Not filing a patent** — published as prior art instead; sales/licensing don't require one.
- **Not trying to "close" the open-source code** — impossible for released versions, and unnecessary; value is in brand + service + execution.
- **Not running a server that holds credentials** — by design; it's our privacy moat and a ToS shield.
- **Not promising foreign IP rights** — likely already forfeited by public disclosure; we won't represent otherwise.

If any partner conversation pushes us to violate one of these, treat it as a signal to slow down and get legal advice — not to quietly say yes.
