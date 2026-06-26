import { describe, it, expect } from 'vitest';
import { parseConfirmRedirectState, hasRecoveryTokens } from '../landing/auth-url-state.js';

describe('parseConfirmRedirectState', () => {
  it('returns success when hash has access_token', () => {
    expect(parseConfirmRedirectState('', '#access_token=abc&refresh_token=def&type=signup'))
      .toEqual({ status: 'success' });
  });

  it('returns success when hash type is signup without token', () => {
    expect(parseConfirmRedirectState('', '#type=signup')).toEqual({ status: 'success' });
  });

  it('returns error from query error param', () => {
    const state = parseConfirmRedirectState('?error=access_denied&error_description=Expired', '');
    expect(state.status).toBe('error');
    expect(state.message).toContain('Expired');
  });

  it('returns error from hash error param', () => {
    const state = parseConfirmRedirectState('', '#error=invalid&error_description=Bad+link');
    expect(state.status).toBe('error');
    expect(state.message).toContain('Bad');
  });

  it('returns unknown when no hash or error', () => {
    expect(parseConfirmRedirectState('', '')).toEqual({ status: 'unknown' });
  });
});

describe('hasRecoveryTokens', () => {
  it('accepts recovery tokens', () => {
    expect(hasRecoveryTokens('#access_token=abc&type=recovery')).toBe(true);
  });

  it('accepts invite tokens', () => {
    expect(hasRecoveryTokens('access_token=abc&type=invite')).toBe(true);
  });

  it('rejects signup tokens', () => {
    expect(hasRecoveryTokens('#access_token=abc&type=signup')).toBe(false);
  });

  it('rejects missing type with access_token', () => {
    expect(hasRecoveryTokens('#access_token=abc')).toBe(false);
  });

  it('rejects empty hash', () => {
    expect(hasRecoveryTokens('')).toBe(false);
  });
});
