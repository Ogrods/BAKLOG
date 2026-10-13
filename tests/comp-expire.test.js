import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const URL_BASE = 'https://demo.supabase.co';

function makeFetch({ users, pending = [] }) {
  return vi.fn(async (url, init = {}) => {
    const u = String(url);
    const method = (init.method || 'GET').toUpperCase();
    if (u.includes('/auth/v1/admin/users?')) return { ok: true, json: async () => ({ users }) };
    if (u.includes('/rest/v1/polar_pending_entitlements') && method === 'GET') {
      return { ok: true, json: async () => pending };
    }
    if (u.includes('/rest/v1/polar_pending_entitlements') && method === 'PATCH') {
      return { ok: true, text: async () => '' };
    }
    const m = u.match(/\/auth\/v1\/admin\/users\/([^/?]+)$/);
    if (m) {
      if (method === 'GET') {
        const user = users.find((x) => x.id === m[1]);
        return { ok: true, json: async () => user };
      }
      return { ok: true, json: async () => ({}) };
    }
    if (u === 'https://api.resend.com/emails') return { ok: true, text: async () => '' };
    throw new Error(`unexpected fetch ${method} ${u}`);
  });
}

async function runCron({ users, pending, auth = 'Bearer cron-secret' }) {
  vi.resetModules();
  const fetchMock = makeFetch({ users, pending });
  vi.stubGlobal('fetch', fetchMock);
  const mod = await import('../web/api/comp-expire.js');
  const res = await mod.default.fetch(new Request('https://baklog.app/api/comp-expire', {
    headers: auth ? { authorization: auth } : {},
  }));
  return { res, json: await res.json(), fetchMock };
}

const puts = (fetchMock) =>
  fetchMock.mock.calls
    .filter(([, init]) => String(init?.method || '').toUpperCase() === 'PUT')
    .map(([u, init]) => ({ id: String(u).split('/').pop(), meta: JSON.parse(init.body).app_metadata }));

describe('comp-expire cron', () => {
  beforeEach(() => {
    process.env.CRON_SECRET = 'cron-secret';
    process.env.SUPABASE_URL = URL_BASE;
    process.env.SUPABASE_SERVICE_ROLE_KEY = 'service-key';
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    for (const k of ['CRON_SECRET', 'RESEND_API_KEY', 'NOTIFY_FROM', 'NOTIFY_TO']) delete process.env[k];
  });

  it('rejects calls without the cron secret', async () => {
    const { res } = await runCron({ users: [], auth: 'Bearer wrong' });
    expect(res.status).toBe(401);
  });

  it('expires only unpaid comps whose end date has passed', async () => {
    const users = [
      { id: 'u1', email: 'old@example.com', app_metadata: { plan: 'pro', comp_until: '2020-01-01', beta: true } },
      { id: 'u2', email: 'future@example.com', app_metadata: { plan: 'pro', comp_until: '2999-01-01' } },
      { id: 'u3', email: 'paid@example.com', app_metadata: { plan: 'pro', paid: true, comp_until: '2020-01-01' } },
      { id: 'u4', email: 'forever@example.com', app_metadata: { plan: 'pro' } },
    ];
    const { json, fetchMock } = await runCron({ users });
    expect(json).toMatchObject({ ok: true, expired: 1, applied: 0 });
    expect(puts(fetchMock)).toEqual([{ id: 'u1', meta: { plan: 'free', beta: true } }]);
  });

  it('applies pending purchases only to confirmed accounts and emails a summary', async () => {
    process.env.RESEND_API_KEY = 're_test';
    process.env.NOTIFY_FROM = 'n@baklog.app';
    process.env.NOTIFY_TO = 'f@example.com';
    const users = [
      { id: 'c1', email: 'Confirmed@example.com', email_confirmed_at: '2026-10-01T00:00:00Z', app_metadata: {} },
      { id: 'n1', email: 'unconfirmed@example.com', email_confirmed_at: null, app_metadata: {} },
    ];
    const pending = [
      { email: 'confirmed@example.com', plan: 'pro', applied_at: null },
      { email: 'unconfirmed@example.com', plan: 'pro', applied_at: null },
    ];
    const { json, fetchMock } = await runCron({ users, pending });
    expect(json).toMatchObject({ expired: 0, applied: 1 });
    const written = puts(fetchMock);
    expect(written.map((p) => p.id)).toEqual(['c1']);
    expect(written[0].meta).toMatchObject({ plan: 'pro', paid: true });
    const mail = fetchMock.mock.calls.find(([u]) => String(u) === 'https://api.resend.com/emails');
    expect(JSON.parse(mail[1].body).subject).toContain('1 pending applied');
  });
});
