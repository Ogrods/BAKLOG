import { describe, it, expect } from 'vitest';
import {
  metaText,
  metaHtml,
  renderMetaPart,
  renderMetaParts,
} from '../js/spotlight-meta.js';

describe('spotlight-meta', () => {
  it('escapes {text} and passes {html} through', () => {
    expect(renderMetaPart(metaText('<img src=x onerror=1>'))).toBe(
      '&lt;img src=x onerror=1&gt;',
    );
    expect(renderMetaPart(metaHtml('<strong>80%</strong>'))).toBe(
      '<strong>80%</strong>',
    );
  });

  it('treats legacy strings as trusted HTML', () => {
    expect(renderMetaPart('<strong>1</strong>')).toBe('<strong>1</strong>');
  });

  it('joins parts with middle dots', () => {
    expect(
      renderMetaParts([metaText('a & b'), metaHtml('<em>c</em>')]),
    ).toBe('a &amp; b · <em>c</em>');
  });
});
