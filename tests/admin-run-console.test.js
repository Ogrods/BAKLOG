import { describe, expect, it } from 'vitest';
import { classifyLineKind } from '../admin/run-console.js';

describe('classifyLineKind', () => {
  it('maps stderr stream to stderr kind', () => {
    expect(classifyLineKind('something broke', 'stderr')).toBe('stderr');
  });

  it('maps command lines starting with $', () => {
    expect(classifyLineKind('$ python build_free_claims.py', 'stdout')).toBe('cmd');
  });

  it('maps bracketed meta lines', () => {
    expect(classifyLineKind('[reconnected · Build free claims feed running]', 'stdout')).toBe('meta');
  });

  it('maps bracketed warn/error lines', () => {
    expect(classifyLineKind('[stream dropped — reconnecting in 2s…]', 'stdout')).toBe('warn');
    expect(classifyLineKind('[Build: failed]', 'stdout')).toBe('warn');
  });

  it('defaults to stdout', () => {
    expect(classifyLineKind('Fetched 42 items', 'stdout')).toBe('stdout');
    expect(classifyLineKind('plain line')).toBe('stdout');
  });
});
