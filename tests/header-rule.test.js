import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const APP_CSS = readFileSync(join(import.meta.dirname, '..', 'app.css'), 'utf8');

function extractRuleBlock(css, selector) {
  const re = new RegExp(`${selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*\\{([^}]*)\\}`, 'm');
  const match = css.match(re);
  return match?.[1] ?? '';
}

describe('header bottom rule CSS', () => {
  it('puts the divider on the nav row, not the full header block', () => {
    const headerBlock = extractRuleBlock(APP_CSS, 'header.app-header');
    const rowBlock = extractRuleBlock(APP_CSS, '.app-header-row');
    expect(headerBlock).not.toMatch(/box-shadow:\s*0\s+1px\s+0\s+var\(--border-subtle\)/);
    expect(rowBlock).toMatch(/box-shadow:\s*0\s+1px\s+0\s+var\(--border-subtle\)/);
  });

  it('documents why summary chips must not own the header rule', () => {
    const INDEX_HTML = readFileSync(join(import.meta.dirname, '..', 'index.html'), 'utf8');
    const headerClose = INDEX_HTML.indexOf('</header>');
    const summaryInHeader = INDEX_HTML.indexOf('id="summary"') < headerClose;
    expect(summaryInHeader).toBe(true);
  });
});
