# BAKLOG Discord community playbook

Internal reference for running the BAKLOG Discord server from invite-only beta through public launch and beyond. Paste-ready rules live in [DISCORD_RULES.md](DISCORD_RULES.md).

---

## Server purpose and lifecycle

**What this server is for**

- Help people install, connect stores, and use BAKLOG.
- Collect structured bug reports and feature ideas.
- Share backlog screenshots, tips, and general gaming talk.
- Announce releases, changelogs, and downtime.

**What this server is not**

- A place to share store logins, cookies, API keys, or exported credential files.
- Official support for piracy, cracked launchers, or bypassing store auth.
- A replacement for GitHub Issues for reproducible bugs (Discord is for triage and discussion; GitHub is the record).

**Lifecycle phases**

| Phase | Who joins | What changes |
|-------|-----------|--------------|
| **Beta (now)** | Invite-only testers | Beta channels active; `#known-issues` pinned; breaking changes expected |
| **Public launch** | Open or wider invite | Remove beta-only channels and beta addendum from `#rules`; keep `#changelog` and support channels |
| **Steady state** | Anyone interested in BAKLOG | Same structure minus beta artifacts; `Beta Tester` role kept as a grandfathered badge |

**Design principle:** Permanent rules, channels, and roles should not hardcode "beta." Beta-only pieces are labeled below so you can delete them at launch without rewriting the core server.

---

## Channel structure

Organize categories top to bottom. Lock `#rules`, `#announcements`, and `#changelog` to read-only for `@everyone` except staff.

### Info (permanent)

| Channel | Purpose | Notes |
|---------|---------|-------|
| `#welcome` | Short intro, links, how to get Verified | Pin: setup link, rules link, FAQ link |
| `#rules` | Paste content from [DISCORD_RULES.md](DISCORD_RULES.md) | Update only the beta addendum during beta |
| `#announcements` | Releases, invites, major news | @everyone sparingly; prefer `@Verified` for non-critical posts |
| `#changelog` | Version-by-version notes | Mirror GitHub release notes; one post per release |
| `#faq` | Curated answers | Link to [BETA_SETUP.md](BETA_SETUP.md) and README; mods edit pins |

### Support (permanent)

| Channel | Purpose | Posting format |
|---------|---------|----------------|
| `#setup-help` | Install, Python, Chrome, first run | OS, BAKLOG version, what you tried, error text (no secrets) |
| `#connections-help` | Store Connect, fetcher auth, platform limits | Store name, OS, connected or not (no cookies or screenshots of login screens with tokens) |
| `#bug-reports` | Repro steps, logs, screenshots | Template below |
| `#feature-requests` | Ideas and UX feedback | One idea per thread if possible |

**Suggested bug report template** (pin in `#bug-reports`):

```
**BAKLOG version:**
**OS:**
**Profile:** (default / named)
**Steps:**
**Expected:**
**Actual:**
**Logs/screenshots:** (redact paths and secrets)
```

### Community (permanent)

| Channel | Purpose |
|---------|---------|
| `#general` | BAKLOG and gaming chat |
| `#showcase` | Dashboard screenshots, backlog stats, marquee shots |
| `#off-topic` | Everything else; keep it civil |

### Beta-only (remove at public launch)

| Channel | Purpose |
|---------|---------|
| `#beta-lounge` | Early tester discussion, rough edges, venting |
| `#known-issues` | Active bugs staff are tracking; link to GitHub when filed |

At launch: archive or delete `#beta-lounge` and `#known-issues`, remove the beta addendum from `#rules`, and post one `#announcements` note that the server is open to all users.

### Staff (hidden from @everyone)

| Channel | Purpose |
|---------|---------|
| `#mod-log` | Warnings, mutes, bans, credential-leak incidents |
| `#staff-chat` | Coordination, escalations |

---

## Role layout

Create roles in this order (highest hoisted first). Use color sparingly; one accent for staff, one for badges.

| Role | Who gets it | Permissions / intent |
|------|-------------|----------------------|
| **Owner** | You (and co-founders if any) | Full admin |
| **Mod** | Trusted volunteers | Manage messages, timeout, kick; no server delete |
| **Bot** | Carl-bot, Welcomer, etc. | As needed for automation |
| **Beta Tester** | Invite wave members during beta | Access to `#beta-lounge`; after launch, cosmetic badge only |
| **Verified** | Everyone who agreed to rules | Gate for `#general`, support, and community channels |
| **Member** | Default on join | Read `#welcome` and `#rules` only until Verified |

**At public launch**

- Stop assigning **Beta Tester** to new joins; keep the role on existing members.
- Optional: rename to **Early Supporter** if you want a neutral long-term label.
- **Verified** stays the gate for posting in community and support channels.

**Permission sketch**

- `@everyone`: read `#welcome`, `#rules`; no send until Verified.
- **Verified**: send in Info (except locked), Support, Community; no `@everyone` mention.
- **Mod**: all public channels + `#mod-log`; manage messages and timeouts.
- **Owner**: everything including `#staff-chat` and role management.

---

## Moderation guidelines

### Escalation ladder

1. **Reminder** - Public or DM: point to the relevant rule and channel.
2. **Warning** - Log in `#mod-log` with user, rule, date, and mod.
3. **Timeout** - 1 hour to 7 days depending on severity and repeat behavior.
4. **Kick** - For clear bad faith or after repeated timeouts; they may rejoin if invite allows.
5. **Ban** - Harassment, hate, illegal content, deliberate credential leaks, or repeated kicks.

Staff decisions are final for server membership. Appeals go to Owner via DM, not public drama threads.

### What to log in `#mod-log`

- Warnings, timeouts, kicks, bans (user ID, action, reason, mod, timestamp).
- Any message deleted for containing **credentials, cookies, API keys, or full library exports with PII**.
- Escalations and policy edge cases (no need to paste message content if it contained secrets; note "credential leak - message purged").

### Private data and security incidents

BAKLOG stores high-value secrets on the user's machine (see [SECURITY.md](../SECURITY.md)). In Discord:

- **Never** ask users to paste `.env`, `secrets.bin`, NPSSO, session cookies, or Connect browser dumps.
- If someone posts credentials: delete immediately, DM them to rotate/re-connect that store, log in `#mod-log`, timeout if intentional.
- Screenshots: ask for redacted UI shots; no full window dumps of Connections or browser devtools Network tabs with cookies.
- Library JSON exports in `#showcase` are fine for game titles and stats; blur or omit file paths that reveal usernames or home directories.

### Spam, promo, and piracy

- No unsolicited ads, referral links, or "check out my server" without mod approval.
- No piracy, cracked store clients, or instructions to bypass Connect auth.
- Store discussion is fine; enabling theft or account sharing is not.

### DMs and harassment

- Mods may DM users for warnings; users may DM mods for help.
- Harassment in DMs after a server interaction is still a ban issue if reported with evidence.
- Do not encourage dogpiling or brigading other communities or stores.

---

## Onboarding flow

### 1. Join

User lands in `#welcome` only (Member role, not Verified).

### 2. Rules gate

Use one of:

- **Discord Server Onboarding** - Rules acceptance grants **Verified**, or
- **Reaction role** - React in `#rules` to get **Verified** (Carl-bot / similar).

Do not grant **Beta Tester** until you have confirmed they are on the invite list (manual or invite-link role).

### 3. Welcome message (bot or pinned template)

```
Welcome to the BAKLOG community.

BAKLOG is a local-first backlog tool. Your library and store sessions stay on your machine.

Before you post:
1. Read #rules and accept them to get Verified.
2. New here? See #faq and the setup guide (link in #welcome pin).
3. Bugs go in #bug-reports with OS, version, and steps.
4. Never share store logins, cookies, or API keys in any channel.

Glad you are here.
```

### 4. First five minutes (pin in `#welcome`)

1. Read `#rules` and get **Verified**.
2. Install from the release link in the pin (or clone-and-run per [BETA_SETUP.md](BETA_SETUP.md)).
3. Stuck on setup? `#setup-help`. Store Connect issues? `#connections-help`.
4. Found a bug? `#bug-reports` with the template.
5. Want to show off your backlog? `#showcase`.

### 5. Beta-specific (remove at launch)

- Point new testers to `#beta-lounge` and `#known-issues`.
- Remind them backups live next to the app folder; beta builds may break profile or data formats.

---

## Maintenance checklist

**Weekly (beta)**

- Triage `#bug-reports`; open GitHub issues for reproducible bugs.
- Update `#known-issues` from open issues.
- Scan for accidental secret posts.

**Per release**

- Post to `#announcements` and `#changelog`.
- Update `#faq` if setup steps changed.

**At public launch**

- Delete beta addendum from `#rules` (see [DISCORD_RULES.md](DISCORD_RULES.md)).
- Archive `#beta-lounge` and `#known-issues`.
- Announce open membership policy in `#announcements`.
- Keep **Beta Tester** / **Early Supporter** on OGs only.

---

## Quick links for pins

- Setup: [BETA_SETUP.md](BETA_SETUP.md) (GitHub raw or docs site when available)
- Security / what not to share: [SECURITY.md](../SECURITY.md)
- Rules paste block: [DISCORD_RULES.md](DISCORD_RULES.md)
