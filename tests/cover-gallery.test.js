/**
 * Tests for js/cover-gallery.js — lightbox image sizing.
 */

import { describe, expect, it, beforeEach, afterEach } from 'vitest';
import { clampGalleryImage } from '../js/cover-gallery.js';

describe('clampGalleryImage', () => {
  const origInnerWidth = window.innerWidth;
  const origInnerHeight = window.innerHeight;

  afterEach(() => {
    Object.defineProperty(window, 'innerWidth', { value: origInnerWidth, configurable: true });
    Object.defineProperty(window, 'innerHeight', { value: origInnerHeight, configurable: true });
  });

  beforeEach(() => {
    Object.defineProperty(window, 'innerWidth', { value: 1200, configurable: true });
    Object.defineProperty(window, 'innerHeight', { value: 800, configurable: true });
  });

  it('clamps to natural size when smaller than viewport caps', () => {
    const img = document.createElement('img');
    Object.defineProperty(img, 'naturalWidth', { value: 600, configurable: true });
    Object.defineProperty(img, 'naturalHeight', { value: 900, configurable: true });
    clampGalleryImage(img);
    expect(img.style.maxWidth).toBe('600px');
    expect(img.style.maxHeight).toBe('680px');
  });

  it('uses viewport caps when natural size is larger', () => {
    const img = document.createElement('img');
    Object.defineProperty(img, 'naturalWidth', { value: 2000, configurable: true });
    Object.defineProperty(img, 'naturalHeight', { value: 3000, configurable: true });
    clampGalleryImage(img);
    expect(img.style.maxWidth).toBe('1080px');
    expect(img.style.maxHeight).toBe('680px');
  });
});
