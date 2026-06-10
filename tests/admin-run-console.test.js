import { describe, expect, it } from 'vitest';
import { classifyLineKind, isJobFailure, jobFailureError } from '../admin/run-console.js';

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

describe('isJobFailure', () => {
  it('treats non-zero exit codes as failure', () => {
    expect(isJobFailure({ status: 'done', exit_code: 0 })).toBe(false);
    expect(isJobFailure({ status: 'done', exit_code: 2 })).toBe(true);
    expect(isJobFailure({ status: 'done', exit_code: 3 })).toBe(true);
  });

  it('treats failed status as failure even without exit code', () => {
    expect(isJobFailure({ status: 'failed' })).toBe(true);
  });
});

describe('jobFailureError', () => {
  it('maps fetcher exit codes to explicit messages', () => {
    expect(jobFailureError('Fetch sources', { exit_code: 2 }).message).toMatch(/refused to overwrite/);
    expect(jobFailureError('Fetch sources', { exit_code: 3 }).message).toMatch(/refused drift/);
  });
});
