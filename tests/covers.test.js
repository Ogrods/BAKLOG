/**
 * Tests for js/covers.js — portrait cover landscape letterboxing helpers.
 */

import { describe, expect, it, beforeEach } from 'vitest';
import {
  portraitCoverImgSelector,
  portraitCoverImgHtml,
  syncCoverFits,
} from '../js/covers.js';

describe('portraitCoverImgSelector', () => {
  it('includes claim row and admin thumb classes', () => {
    expect(portraitCoverImgSelector).toContain('img.claim-row-cover');
    expect(portraitCoverImgSelector).toContain('img.claim-cover-thumb');
  });
});

describe('portraitCoverImgHtml', () => {
  beforeEach(() => {
    window.__landscapeCovers = new Set();
  });

  it('returns empty string when url is missing', () => {
    expect(portraitCoverImgHtml('', 'claim-row-cover')).toBe('');
  });

  it('emits cover-wrap with markLandscape onload', () => {
    const html = portraitCoverImgHtml('https://cdn.example/cover.jpg', 'claim-row-cover', 'claim-row-cover-wrap');
    expect(html).toContain('cover-wrap claim-row-cover-wrap');
    expect(html).toContain('claim-row-cover');
    expect(html).toContain('onload="window.markLandscape(this)"');
  });

  it('applies cached landscape class from coverLandscapeAttr', () => {
    window.__landscapeCovers.add('https://cdn.example/wide.jpg');
    const html = portraitCoverImgHtml('https://cdn.example/wide.jpg', 'claim-cover-thumb', 'claim-cover-wrap');
    expect(html).toContain('landscape');
  });
});

describe('syncCoverFits', () => {
  beforeEach(() => {
    window.__landscapeCovers = new Set();
    document.body.innerHTML = '';
  });

  it('marks landscape claim-row-cover images after load', async () => {
    const root = document.createElement('div');
    root.innerHTML = `
      <span class="cover-wrap claim-row-cover-wrap">
        <img class="claim-row-cover" src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7" alt="" />
      </span>`;
    document.body.appendChild(root);
    const img = root.querySelector('img.claim-row-cover');
    Object.defineProperty(img, 'naturalWidth', { value: 460, configurable: true });
    Object.defineProperty(img, 'naturalHeight', { value: 215, configurable: true });
    Object.defineProperty(img, 'complete', { value: true, configurable: true });
    syncCoverFits(root);
    expect(img.classList.contains('landscape')).toBe(true);
    expect(img.closest('.cover-wrap').classList.contains('landscape')).toBe(true);
  });
});
