/** Public marketing copy must not over-claim auto-sync / background behavior. */
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const BANNED = [
  /set-and-forget/i,
  /syncs on its own/i,
  /stays updated automatically/i,
  /new purchases show up on their own/i,
  /it syncs itself/i,
  /syncs automatically/i,
];

const FILES = [
  'landing/index.html',
  'marketing/one-pager.html',
  'marketing/index.html',
];

describe('marketing copy guardrails', () => {
  for (const rel of FILES) {
    it(`${rel} avoids over-claimed auto-sync phrases`, () => {
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

  it('one-pager does not list system tray as shipped', () => {
    const text = readFileSync('marketing/one-pager.html', 'utf8');
    const shippedBlock = text.slice(
      text.indexOf('Product (shipped)'),
      text.indexOf('Planned') > -1 ? text.indexOf('Planned') : text.length,
    );
    expect(shippedBlock.toLowerCase()).not.toMatch(/system tray/);
  });
});
