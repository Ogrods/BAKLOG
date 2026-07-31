import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

const authGate = vi.hoisted(() => ({
  isAccountAuthMode: vi.fn(() => false),
  getAccessToken: vi.fn(() => null),
  whenAuthReady: vi.fn(() => Promise.resolve()),
  refreshAccessToken: vi.fn(async () => null),
  handleApiUnauthorized: vi.fn(),
}));

const errorBoundary = vi.hoisted(() => ({
  reportError: vi.fn(),
}));

vi.mock('../js/auth-gate.js', () => ({
  isAccountAuthMode: authGate.isAccountAuthMode,
  getAccessToken: authGate.getAccessToken,
  whenAuthReady: authGate.whenAuthReady,
  refreshAccessToken: authGate.refreshAccessToken,
  handleApiUnauthorized: authGate.handleApiUnauthorized,
}));

vi.mock('../js/error-boundary.js', () => ({
  reportError: errorBoundary.reportError,
}));

describe('api-client update-restart network suppress', () => {
  beforeEach(() => {
    errorBoundary.reportError.mockReset();
    authGate.isAccountAuthMode.mockReturnValue(false);
    window.__baklogSuppressNetworkErrors = false;
    try {
      sessionStorage.removeItem('baklog.suppressNetworkErrors');
    } catch {
      /* ignore */
    }
  });

  afterEach(() => {
    window.__baklogSuppressNetworkErrors = false;
    try {
      sessionStorage.removeItem('baklog.suppressNetworkErrors');
    } catch {
      /* ignore */
    }
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it('reports NetworkError when suppress is off', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch');
      }),
    );
    const { baklogFetch } = await import('../js/api-client.js');
    await expect(baklogFetch('/api/update/status')).rejects.toMatchObject({
      name: 'NetworkError',
    });
    expect(errorBoundary.reportError).toHaveBeenCalled();
    expect(String(errorBoundary.reportError.mock.calls[0][0].message)).toContain(
      '/api/update/status',
    );
  });

  it('skips reportError when window suppress flag is set', async () => {
    window.__baklogSuppressNetworkErrors = true;
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch');
      }),
    );
    const { baklogFetch } = await import('../js/api-client.js');
    await expect(baklogFetch('/api/update/apply-result')).rejects.toMatchObject({
      name: 'NetworkError',
    });
    expect(errorBoundary.reportError).not.toHaveBeenCalled();
  });

  it('skips reportError when sessionStorage suppress key is set', async () => {
    sessionStorage.setItem('baklog.suppressNetworkErrors', '1');
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch');
      }),
    );
    const { baklogFetch } = await import('../js/api-client.js');
    await expect(baklogFetch('/api/update/status')).rejects.toMatchObject({
      name: 'NetworkError',
    });
    expect(errorBoundary.reportError).not.toHaveBeenCalled();
  });
});
