import { describe, it, expect } from 'vitest';
import { formatPlatformLabel, formatPlatformList } from '../js/platform-labels.js';

describe('platform-labels', () => {
  it('maps sys.platform ids to friendly names', () => {
    expect(formatPlatformLabel('win32')).toBe('Windows');
    expect(formatPlatformLabel('darwin')).toBe('macOS');
    expect(formatPlatformLabel('linux')).toBe('Linux');
  });

  it('formatPlatformList joins and falls back when empty', () => {
    expect(formatPlatformList(['win32', 'darwin'])).toBe('Windows, macOS');
    expect(formatPlatformList([])).toBe('Windows');
  });
});
