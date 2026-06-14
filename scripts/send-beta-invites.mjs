/**
 * Send BAKLOG beta invite emails to waitlist signups (maintainer one-off).
 *
 * Reuses the same stack as the landing waitlist: pulls not-yet-invited rows from
 * the Supabase `waitlist` table (service_role), emails each one a beta invite via
 * Resend with a link to the GitHub release page, then stamps `invited_at` so the
 * next wave skips them. Not a Vercel function - run it locally on demand.
 *
 * SAFE BY DEFAULT: prints what it would do and sends nothing unless you pass
 * --send. Use --limit N to size a wave and --email you@x.com to test one address.
 *
 * Env (set in your shell, or in landing/.env which this script auto-loads):
 *   SUPABASE_URL               - same project as the waitlist function
 *   SUPABASE_SERVICE_ROLE_KEY  - service_role key (server-only; never in browser)
 *   RESEND_API_KEY             - Resend API key
 *   BETA_FROM   (or NOTIFY_FROM)    - sender on a Resend-verified domain
 *   BETA_REPLY_TO (or NOTIFY_TO)    - optional reply-to address
 *   BETA_RELEASE_URL           - optional; defaults to the repo releases page
 *
 * Examples:
 *   node scripts/send-beta-invites.mjs                      # dry run, first 25
 *   node scripts/send-beta-invites.mjs --limit 10          # dry run, first 10
 *   node scripts/send-beta-invites.mjs --email me@you.com  # dry run, single test
 *   node scripts/send-beta-invites.mjs --email me@you.com --send   # real test send
 *   node scripts/send-beta-invites.mjs --limit 20 --send   # real wave of 20
 */
import fs from 'node:fs';
import path from 'node:path';

const root = path.resolve(import.meta.dirname, '..');

const DEFAULT_RELEASE_URL = 'https://github.com/Ogrods/BAKLOG/releases/latest';
const DEFAULT_LIMIT = 25;
const SEND_DELAY_MS = 600; // gentle pacing so Resend does not throttle the batch

/** Load KEY=VALUE pairs from a .env file without overriding the real env. */
function loadEnvFile(file) {
  let text;
  try {
    text = fs.readFileSync(file, 'utf8');
  } catch {
    return;
  }
  for (const line of text.split(/\r?\n/)) {
    const m = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$/);
    if (!m) continue;
    const key = m[1];
    if (process.env[key] !== undefined) continue;
    let val = m[2].trim();
    if (
      (val.startsWith('"') && val.endsWith('"')) ||
      (val.startsWith("'") && val.endsWith("'"))
    ) {
      val = val.slice(1, -1);
    }
    process.env[key] = val;
  }
}

function parseArgs(argv) {
  const args = { limit: DEFAULT_LIMIT, send: false, email: null, resendInvited: false };
  for (let i = 0; i < argv.length; i += 1) {
    const a = argv[i];
    if (a === '--send') args.send = true;
    else if (a === '--dry-run') args.send = false;
    else if (a === '--resend-invited') args.resendInvited = true;
    else if (a === '--limit') args.limit = Number(argv[++i]);
    else if (a.startsWith('--limit=')) args.limit = Number(a.slice('--limit='.length));
    else if (a === '--email') args.email = String(argv[++i] || '').trim();
    else if (a.startsWith('--email=')) args.email = a.slice('--email='.length).trim();
    else if (a === '--help' || a === '-h') args.help = true;
    else {
      console.error(`Unknown argument: ${a}`);
      process.exit(2);
    }
  }
  if (!Number.isFinite(args.limit) || args.limit <= 0) args.limit = DEFAULT_LIMIT;
  return args;
}

function buildEmail(releaseUrl) {
  const subject = 'Your BAKLOG beta invite is ready';
  const text = `Your BAKLOG beta spot is open.

Thanks for joining the waitlist. The Windows beta is ready to install.

Download it here: ${releaseUrl}

Quick start:
- Grab BAKLOG-v*-Setup.exe (or the portable zip) from the release page.
- If Windows SmartScreen warns about an unknown publisher, click More info, then Run anyway. The build is not code-signed yet.
- Launch BAKLOG, open the Connections tab, and connect the stores you use.

Your library and credentials stay on your machine. Nothing is uploaded by default.

Hit a snag? Reply to this email or use Report a bug in the app menu.

- The BAKLOG team
https://baklog.app`;

  const html = `<!doctype html>
<html>
  <body style="margin:0;background:#0f172a;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#e2e8f0;">
    <div style="max-width:520px;margin:0 auto;padding:32px 24px;">
      <h1 style="font-size:20px;margin:0 0 16px;color:#f8fafc;">Your BAKLOG beta invite is ready</h1>
      <p style="font-size:15px;line-height:1.6;margin:0 0 16px;">Thanks for joining the waitlist. The Windows beta is ready to install.</p>
      <p style="margin:0 0 20px;">
        <a href="${releaseUrl}" style="display:inline-block;background:#38bdf8;color:#0f172a;font-weight:600;text-decoration:none;padding:10px 18px;border-radius:8px;">Download the beta</a>
      </p>
      <p style="font-size:15px;line-height:1.6;margin:0 0 8px;">Quick start:</p>
      <ul style="font-size:15px;line-height:1.6;margin:0 0 16px;padding-left:20px;">
        <li>Grab BAKLOG-v*-Setup.exe (or the portable zip) from the release page.</li>
        <li>If Windows SmartScreen warns about an unknown publisher, click More info, then Run anyway. The build is not code-signed yet.</li>
        <li>Launch BAKLOG, open the Connections tab, and connect the stores you use.</li>
      </ul>
      <p style="font-size:15px;line-height:1.6;margin:0 0 16px;">Your library and credentials stay on your machine. Nothing is uploaded by default.</p>
      <p style="font-size:15px;line-height:1.6;margin:0 0 24px;">Hit a snag? Reply to this email or use Report a bug in the app menu.</p>
      <p style="font-size:14px;line-height:1.6;margin:0;color:#94a3b8;">- The BAKLOG team<br /><a href="https://baklog.app" style="color:#38bdf8;">baklog.app</a></p>
    </div>
  </body>
</html>`;

  return { subject, text, html };
}

async function fetchWaitlist({ url, key, limit, resendInvited }) {
  const params = new URLSearchParams({
    select: 'email,created_at,invited_at',
    order: 'created_at.asc',
    limit: String(limit),
  });
  if (!resendInvited) params.set('invited_at', 'is.null');
  const r = await fetch(`${url}/rest/v1/waitlist?${params.toString()}`, {
    headers: { apikey: key, Authorization: `Bearer ${key}` },
  });
  if (!r.ok) {
    const detail = await r.text().catch(() => '');
    throw new Error(`Supabase select ${r.status}: ${detail}`);
  }
  return r.json();
}

async function markInvited({ url, key, email, time }) {
  const params = new URLSearchParams({ email: `eq.${email}` });
  const r = await fetch(`${url}/rest/v1/waitlist?${params.toString()}`, {
    method: 'PATCH',
    headers: {
      apikey: key,
      Authorization: `Bearer ${key}`,
      'Content-Type': 'application/json',
      Prefer: 'return=minimal',
    },
    body: JSON.stringify({ invited_at: time }),
  });
  if (!r.ok) {
    const detail = await r.text().catch(() => '');
    throw new Error(`Supabase update ${r.status}: ${detail}`);
  }
}

async function sendEmail({ apiKey, from, to, replyTo, subject, text, html }) {
  const payload = { from, to, subject, text, html };
  if (replyTo) payload.reply_to = replyTo;
  const r = await fetch('https://api.resend.com/emails', {
    method: 'POST',
    headers: { Authorization: `Bearer ${apiKey}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!r.ok) {
    const detail = await r.text().catch(() => '');
    throw new Error(`Resend ${r.status}: ${detail}`);
  }
}

const sleep = (ms) => new Promise((res) => setTimeout(res, ms));

async function main() {
  loadEnvFile(path.join(root, 'landing', '.env'));
  loadEnvFile(path.join(root, '.env'));

  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    console.log('Send BAKLOG beta invites. See header of scripts/send-beta-invites.mjs for usage.');
    return;
  }

  const supabaseUrl = (process.env.SUPABASE_URL || '').trim().replace(/\/$/, '');
  const serviceKey = (process.env.SUPABASE_SERVICE_ROLE_KEY || '').trim();
  const apiKey = (process.env.RESEND_API_KEY || '').trim();
  const from = (process.env.BETA_FROM || process.env.NOTIFY_FROM || '').trim();
  const replyTo = (process.env.BETA_REPLY_TO || process.env.NOTIFY_TO || '').trim();
  const releaseUrl = (process.env.BETA_RELEASE_URL || DEFAULT_RELEASE_URL).trim();

  const missing = [];
  if (!apiKey) missing.push('RESEND_API_KEY');
  if (!from) missing.push('BETA_FROM (or NOTIFY_FROM)');
  if (!args.email) {
    if (!supabaseUrl) missing.push('SUPABASE_URL');
    if (!serviceKey) missing.push('SUPABASE_SERVICE_ROLE_KEY');
  }
  if (missing.length) {
    console.error(`Missing env: ${missing.join(', ')}`);
    console.error('Set them in your shell or landing/.env, then re-run.');
    process.exit(1);
  }

  let recipients;
  if (args.email) {
    recipients = [{ email: args.email, created_at: null, invited_at: null }];
  } else {
    recipients = await fetchWaitlist({
      url: supabaseUrl,
      key: serviceKey,
      limit: args.limit,
      resendInvited: args.resendInvited,
    });
  }

  const mode = args.send ? 'SEND' : 'DRY RUN';
  console.log(`[${mode}] from: ${from}`);
  console.log(`[${mode}] release link: ${releaseUrl}`);
  console.log(
    `[${mode}] recipients: ${recipients.length}` +
      (args.email ? ' (single --email)' : ` (waitlist, limit ${args.limit}, ${args.resendInvited ? 'including already-invited' : 'not-yet-invited only'})`),
  );

  if (!recipients.length) {
    console.log('Nothing to do.');
    return;
  }

  if (!args.send) {
    for (const row of recipients) console.log(`  would email: ${row.email}`);
    console.log('\nDry run only. Re-run with --send to actually email these people.');
    return;
  }

  const { subject, text, html } = buildEmail(releaseUrl);
  let sent = 0;
  let failed = 0;
  for (const row of recipients) {
    const email = row.email;
    try {
      await sendEmail({ apiKey, from, to: email, replyTo, subject, text, html });
      if (!args.email) {
        await markInvited({ url: supabaseUrl, key: serviceKey, email, time: new Date().toISOString() });
      }
      sent += 1;
      console.log(`  sent: ${email}`);
    } catch (err) {
      failed += 1;
      console.error(`  FAILED: ${email} - ${err.message}`);
    }
    await sleep(SEND_DELAY_MS);
  }

  console.log(`\nDone. sent=${sent} failed=${failed}`);
  if (failed) process.exitCode = 1;
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
