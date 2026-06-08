/**
 * Tests for js/dom-util.js — escaping + safe-URL guard.
 */

import { describe, expect, it } from 'vitest';
import { isSafeHttpUrl } from '../js/dom-util.js';

describe('isSafeHttpUrl', () => {
  it('accepts absolute http and https urls', () => {
    expect(isSafeHttpUrl('https://example.com')).toBe(true);
    expect(isSafeHttpUrl('http://example.com/path?q=1#h')).toBe(true);
    expect(isSafeHttpUrl('  https://example.com  ')).toBe(true);
  });

  it('rejects dangerous schemes', () => {
    expect(isSafeHttpUrl('javascript:alert(1)')).toBe(false);
    expect(isSafeHttpUrl('data:text/html,<script>alert(1)</script>')).toBe(false);
    expect(isSafeHttpUrl('vbscript:msgbox(1)')).toBe(false);
    expect(isSafeHttpUrl('file:///etc/passwd')).toBe(false);
  });

  it('rejects protocol-relative, relative, and invalid values', () => {
    expect(isSafeHttpUrl('//evil.com')).toBe(false);
    expect(isSafeHttpUrl('/relative/path')).toBe(false);
    expect(isSafeHttpUrl('not a url')).toBe(false);
    expect(isSafeHttpUrl('')).toBe(false);
    expect(isSafeHttpUrl(null)).toBe(false);
    expect(isSafeHttpUrl(undefined)).toBe(false);
    expect(isSafeHttpUrl(42)).toBe(false);
  });
});
