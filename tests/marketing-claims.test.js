/** Public marketing copy must not over-claim auto-sync / background behavior. */
import { existsSync, readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const BANNED = [
  /set-and-forget/i,
  /syncs on its own/i,
  /stays updated automatically/i,
  /new purchases show up on their own/i,
  /it syncs itself/i,
  /syncs automatically/i,
];

// landing/ is the public marketing surface and is always present in CI.
// marketing/ is kept local-only (gitignored), so guard those assertions
// behind a file-existence check to avoid failing in CI.
const PUBLIC_FILES = ['landing/index.html'];
const LOCAL_FILES = ['marketing/one-pager.html', 'marketing/index.html'];

describe('marketing copy guardrails', () => {
  for (const rel of [...PUBLIC_FILES, ...LOCAL_FILES]) {
    const run = PUBLIC_FILES.includes(rel) || existsSync(rel) ? it : it.skip;
    run(`${rel} avoids over-claimed auto-sync phrases`, () => {
      const text = readFileSync(rel, 'utf8');
      for (const pattern of BANNED) {
        expect(text, `banned phrase ${pattern}`).not.toMatch(pattern);
      }
    });
  }

  it('landing/index.html uses canonical magic-moment numbers', () => {
    const text = readFileSync('landing/index.html', 'utf8');
    expect(text).toMatch(/2,000\+/);
    expect(text).toMatch(/90 sec|~90 seconds|90 seconds/i);
  });

  const onePagerIt = existsSync('marketing/one-pager.html') ? it : it.skip;

  onePagerIt('one-pager lists system tray as shipped', () => {
    const text = readFileSync('marketing/one-pager.html', 'utf8');
    const shippedBlock = text.slice(
      text.indexOf('Product (shipped)'),
      text.indexOf('Business model'),
    );
    expect(shippedBlock.toLowerCase()).toMatch(/system tray/);
  });

  onePagerIt('one-pager keeps cloud sync out of the stat strip', () => {
    const text = readFileSync('marketing/one-pager.html', 'utf8');
    const statStrip = text.slice(
      text.indexOf('stat-strip'),
      text.indexOf('<div class="cols">'),
    );
    expect(statStrip.toLowerCase()).not.toMatch(/cloud sync/);
  });

  onePagerIt('one-pager presents cloud sync in the live paid tier', () => {
    const text = readFileSync('marketing/one-pager.html', 'utf8');
    const paidCard = text.slice(
      text.indexOf('tier-card--paid'),
      text.indexOf('</div>\n    </div>\n\n    <div class="cta-band">'),
    );
    expect(paidCard.toLowerCase()).toMatch(/cloud sync/);
    expect(paidCard).not.toMatch(/#1 roadmap/i);
    expect(paidCard).not.toMatch(/planned/i);
  });

  onePagerIt('one-pager uses $5 flat pricing and free vs paid tiers', () => {
    const text = readFileSync('marketing/one-pager.html', 'utf8');
    expect(text).toMatch(/\$5\/mo/);
    expect(text).not.toMatch(/\$2\.99|\$4\.99/);
    expect(text).toMatch(/tier-grid[\s\S]*Free forever[\s\S]*<h3>Paid<\/h3>/i);
  });

  it('landing/index.html uses Support BAKLOG framing without visible monthly pricing', () => {
    const text = readFileSync('landing/index.html', 'utf8');
    expect(text).not.toMatch(/\$5\/mo/);
    expect(text).not.toMatch(/\$2\.99|\$4\.99/);
    expect(text).toMatch(/Support BAKLOG/);
  });

  it('landing tier table marks cloud sync and deal alerts as Coming on paid', () => {
    const text = readFileSync('landing/index.html', 'utf8');
    const start = text.indexOf('class="tier-compare"');
    expect(start).toBeGreaterThan(-1);
    const end = text.indexOf('</table>', start);
    const table = text.slice(start, end);
    expect(table).toMatch(/Cloud sync[\s\S]*?<td>✕<\/td>[\s\S]*?<td>Coming<\/td>/i);
    expect(table).toMatch(/Deal\/watchlist alerts[\s\S]*?<td>✕<\/td>[\s\S]*?<td>Coming<\/td>/i);
  });

  it('landing tier table keeps queue-all refresh as coming on paid', () => {
    const text = readFileSync('landing/index.html', 'utf8');
    const start = text.indexOf('class="tier-compare"');
    const table = text.slice(start, text.indexOf('</table>', start));
    expect(table).toMatch(/Manual store refresh[\s\S]*coming/i);
  });

  const UNQUALIFIED_TELEMETRY = /\b(?:No|Zero) telemetry\b/gi;

  function assertQualifiedTelemetryCopy(text) {
    let match;
    UNQUALIFIED_TELEMETRY.lastIndex = 0;
    while ((match = UNQUALIFIED_TELEMETRY.exec(text)) !== null) {
      const window = text.slice(match.index, match.index + 80);
      expect(window, `unqualified telemetry near: ${window.slice(0, 40)}…`).toMatch(
        /by default/i,
      );
    }
  }

  const TELEMETRY_CANONICAL_FILES = [
    'landing/index.html',
    'README.md',
    'guide/faq.md',
    'js/sponsored-deals.js',
  ];

  const TELEMETRY_GUARD_FILES = [
    ...TELEMETRY_CANONICAL_FILES,
    'PRIVACY.md',
    'SECURITY.md',
  ];

  for (const rel of TELEMETRY_CANONICAL_FILES) {
    it(`${rel} states no telemetry by default`, () => {
      const text = readFileSync(rel, 'utf8');
      expect(text).toMatch(/no telemetry by default/i);
      assertQualifiedTelemetryCopy(text);
    });
  }

  for (const rel of TELEMETRY_GUARD_FILES) {
    it(`${rel} avoids unqualified telemetry claims`, () => {
      assertQualifiedTelemetryCopy(readFileSync(rel, 'utf8'));
    });
  }

  it('PRIVACY.md matches opt-in telemetry policy', () => {
    const text = readFileSync('PRIVACY.md', 'utf8');
    expect(text).toMatch(/by default/i);
    expect(text).toMatch(/shareAnonStats|share anonymous stats/i);
  });

  it('ARCHITECTURE.md documents network boundaries', () => {
    const text = readFileSync('ARCHITECTURE.md', 'utf8');
    expect(text).toMatch(/Network calls/i);
    expect(text).toMatch(/baklog\.app/);
    expect(text).toMatch(/server\.py/);
  });
});
