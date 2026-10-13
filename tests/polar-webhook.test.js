import { createHmac } from 'node:crypto';
import { describe, expect, it, vi, beforeEach } from 'vitest';

const SUPABASE_URL = 'https://demo.supabase.co';
const SERVICE_KEY = 'service-role-key';
const WEBHOOK_SECRET = 'polar_test_secret';

function signBody(body, secret = WEBHOOK_SECRET) {
  const id = 'msg_test_1';
  const timestamp = String(Math.floor(Date.now() / 1000));
  const mac = createHmac('sha256', secret).update(`${id}.${timestamp}.${body}`).digest('base64');
  return {
    id,
    timestamp,
    signature: `v1,${mac}`,
  };
}

const CONFIRMED_AT = '2026-09-01T00:00:00Z';

async function postWebhook(
  event,
  { secret = WEBHOOK_SECRET, env = {}, appMeta = { beta: true }, confirmedAt = CONFIRMED_AT } = {},
) {
  vi.resetModules();
  process.env.POLAR_WEBHOOK_SECRET = secret;
  process.env.SUPABASE_URL = SUPABASE_URL;
  process.env.SUPABASE_SERVICE_ROLE_KEY = SERVICE_KEY;
  Object.assign(process.env, env);
  const body = JSON.stringify(event);
  const sig = signBody(body, secret);
  const fetchMock = vi.fn(async (url, init) => {
    if (String(url).includes('/rpc/get_user_id_by_email')) {
      return { ok: true, json: async () => '11111111-1111-4111-8111-111111111111' };
    }
    if (String(url).includes('/auth/v1/admin/users/')) {
      const method = (init?.method || 'GET').toUpperCase();
      if (method === 'GET') {
        return {
          ok: true,
          json: async () => ({ id: 'u1', email_confirmed_at: confirmedAt, app_metadata: { ...appMeta } }),
        };
      }
      return { ok: true, json: async () => ({}) };
    }
    if (String(url).includes('/rest/v1/polar_pending_entitlements')) {
      return { ok: true, text: async () => '' };
    }
    if (String(url) === 'https://api.resend.com/emails') return { ok: true, text: async () => '' };
    throw new Error(`unexpected fetch ${url} ${init?.method || ''}`);
  });
  vi.stubGlobal('fetch', fetchMock);
  const mod = await import('../web/api/polar-webhook.js');
  const req = new Request('https://baklog.app/api/polar-webhook', {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      'webhook-id': sig.id,
      'webhook-timestamp': sig.timestamp,
      'webhook-signature': sig.signature,
    },
    body,
  });
  const res = await mod.default.fetch(req);
  const json = await res.json();
  return { res, json, fetchMock };
}

describe('polar-webhook', () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  it('ignores unknown event types with 202', async () => {
    const { res, json } = await postWebhook({ type: 'checkout.created', data: {} });
    expect(res.status).toBe(202);
    expect(json.ok).toBe(true);
    expect(json.ignored).toBe('checkout.created');
  });

  it('sets pro on subscription.active when buyer matches', async () => {
    const { res, json, fetchMock } = await postWebhook({
      type: 'subscription.active',
      data: {
        product: { metadata: { plan: 'pro' } },
        customer: { email: 'buyer@example.com' },
      },
    });
    expect(res.status).toBe(202);
    expect(json.ok).toBe(true);
    expect(json.plan).toBe('pro');
    expect(fetchMock).toHaveBeenCalled();
  });

  it('rejects bad signatures', async () => {
    vi.resetModules();
    process.env.POLAR_WEBHOOK_SECRET = 'server-secret';
    process.env.SUPABASE_URL = SUPABASE_URL;
    process.env.SUPABASE_SERVICE_ROLE_KEY = SERVICE_KEY;
    const body = JSON.stringify({
      type: 'subscription.active',
      data: { product: {}, customer: { email: 'a@b.c' } },
    });
    const sig = signBody(body, 'different-signing-secret');
    const mod = await import('../web/api/polar-webhook.js');
    const res = await mod.default.fetch(new Request('https://baklog.app/api/polar-webhook', {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'webhook-id': sig.id,
        'webhook-timestamp': sig.timestamp,
        'webhook-signature': sig.signature,
      },
      body,
    }));
    expect(res.status).toBe(403);
  });

  it('returns 500 when webhook env is missing', async () => {
    vi.resetModules();
    delete process.env.POLAR_WEBHOOK_SECRET;
    process.env.SUPABASE_URL = SUPABASE_URL;
    process.env.SUPABASE_SERVICE_ROLE_KEY = SERVICE_KEY;
    const mod = await import('../web/api/polar-webhook.js');
    const res = await mod.default.fetch(new Request('https://baklog.app/api/polar-webhook', { method: 'POST', body: '{}' }));
    expect(res.status).toBe(500);
  });

  it('sets pro via external_customer_id without email lookup', async () => {
    const userId = '22222222-2222-4222-8222-222222222222';
    const { res, json, fetchMock } = await postWebhook({
      type: 'order.paid',
      data: {
        product: { metadata: { plan: 'pro' } },
        customer: { external_id: userId, email: 'buyer@example.com' },
      },
    });
    expect(res.status).toBe(202);
    expect(json.plan).toBe('pro');
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/rpc/get_user_id_by_email'))).toBe(false);
    const putCall = fetchMock.mock.calls.find(
      ([url, init]) =>
        String(url).includes('/auth/v1/admin/users/') &&
        String(init?.method || '').toUpperCase() === 'PUT',
    );
    expect(putCall?.[1]?.body).toContain('"plan":"pro"');
    expect(putCall?.[1]?.body).toContain('"beta":true');
  });

  it('downgrades to free on subscription.revoked', async () => {
    const { res, json, fetchMock } = await postWebhook({
      type: 'subscription.revoked',
      data: {
        product: { metadata: { plan: 'pro' } },
        customer: { email: 'buyer@example.com' },
      },
    });
    expect(res.status).toBe(202);
    expect(json.plan).toBe('free');
    const putCall = fetchMock.mock.calls.find(
      ([url, init]) =>
        String(url).includes('/auth/v1/admin/users/') &&
        String(init?.method || '').toUpperCase() === 'PUT',
    );
    expect(putCall?.[1]?.body).toContain('"plan":"free"');
    expect(putCall?.[1]?.body).toContain('"beta":true');
  });

  const putMeta = (fetchMock) => {
    const call = fetchMock.mock.calls.find(
      ([url, init]) =>
        String(url).includes('/auth/v1/admin/users/') &&
        String(init?.method || '').toUpperCase() === 'PUT',
    );
    return JSON.parse(call[1].body).app_metadata;
  };
  const revoked = { type: 'subscription.revoked', data: { product: {}, customer: { email: 'b@example.com' } } };

  it('marks a paying beta tester paid and keeps their comp date', async () => {
    const { json, fetchMock } = await postWebhook(
      { type: 'order.paid', data: { product: {}, customer: { email: 'b@example.com' } } },
      { appMeta: { plan: 'pro', comp_until: '2027-03-31' } },
    );
    expect(json.plan).toBe('pro');
    const meta = putMeta(fetchMock);
    expect(meta).toMatchObject({ plan: 'pro', paid: true, comp_until: '2027-03-31' });
    expect(meta.paid_since).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it('keeps Pro on cancel while the comp grant is still running', async () => {
    const { json, fetchMock } = await postWebhook(revoked, {
      appMeta: { plan: 'pro', paid: true, comp_until: '2999-12-31' },
    });
    expect(json.plan).toBe('pro');
    expect(putMeta(fetchMock)).toEqual({ plan: 'pro', comp_until: '2999-12-31', paid: null, paid_since: null });
  });

  it('drops to free on cancel once the comp grant has ended', async () => {
    const { json, fetchMock } = await postWebhook(revoked, {
      appMeta: { plan: 'pro', paid: true, comp_until: '2020-01-01' },
    });
    expect(json.plan).toBe('free');
    expect(putMeta(fetchMock)).toEqual({ plan: 'free', comp_until: '2020-01-01', paid: null, paid_since: null });
  });

  it('routes an email match with an unconfirmed address to pending without writing metadata', async () => {
    const { res, json, fetchMock } = await postWebhook(
      { type: 'order.paid', data: { product: {}, customer: { email: 'squatter@example.com' } } },
      { confirmedAt: null },
    );
    expect(res.status).toBe(202);
    expect(json).toMatchObject({ matched: false, pending: true });
    expect(fetchMock.mock.calls.some(([, init]) => String(init?.method || '').toUpperCase() === 'PUT')).toBe(false);
    const upsert = fetchMock.mock.calls.find(([u]) => String(u).includes('/rest/v1/polar_pending_entitlements'));
    expect(JSON.parse(upsert[1].body)).toMatchObject({ email: 'squatter@example.com', plan: 'pro' });
  });

  it('ignores an event older than the last applied one', async () => {
    const { res, json, fetchMock } = await postWebhook(
      { type: 'order.paid', data: { created_at: '2026-10-01T00:00:00Z', product: {}, customer: { email: 'b@example.com' } } },
      { appMeta: { plan: 'free', polar_event_at: '2026-10-05T00:00:00.000Z' } },
    );
    expect(res.status).toBe(202);
    expect(json.stale).toBe(true);
    const puts = fetchMock.mock.calls.filter(([, init]) => String(init?.method || '').toUpperCase() === 'PUT');
    expect(puts).toHaveLength(0);
  });

  it('falls back to email when external_id is not a real user', async () => {
    vi.resetModules();
    process.env.POLAR_WEBHOOK_SECRET = WEBHOOK_SECRET;
    process.env.SUPABASE_URL = SUPABASE_URL;
    process.env.SUPABASE_SERVICE_ROLE_KEY = SERVICE_KEY;
    const ghost = '33333333-3333-4333-8333-333333333333';
    const real = '11111111-1111-4111-8111-111111111111';
    const body = JSON.stringify({
      type: 'order.paid',
      data: { product: {}, customer: { external_id: ghost, email: 'buyer@example.com' } },
    });
    const sig = signBody(body);
    const fetchMock = vi.fn(async (url, init) => {
      const u = String(url);
      const method = (init?.method || 'GET').toUpperCase();
      if (u.endsWith(`/admin/users/${ghost}`)) return { ok: false, status: 404, text: async () => 'not found' };
      if (u.includes('/rpc/get_user_id_by_email')) return { ok: true, json: async () => real };
      if (u.endsWith(`/admin/users/${real}`)) {
        return method === 'GET'
          ? {
            ok: true,
            json: async () => ({ email: 'buyer@example.com', email_confirmed_at: CONFIRMED_AT, app_metadata: {} }),
          }
          : { ok: true, json: async () => ({}) };
      }
      throw new Error(`unexpected fetch ${u}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    const mod = await import('../web/api/polar-webhook.js');
    const res = await mod.default.fetch(new Request('https://baklog.app/api/polar-webhook', {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'webhook-id': sig.id,
        'webhook-timestamp': sig.timestamp,
        'webhook-signature': sig.signature,
      },
      body,
    }));
    expect(res.status).toBe(202);
    expect((await res.json()).plan).toBe('pro');
    const put = fetchMock.mock.calls.find(([, init]) => String(init?.method || '').toUpperCase() === 'PUT');
    expect(String(put[0])).toContain(real);
  });

  it('emails the founder on a matched change', async () => {
    const { fetchMock } = await postWebhook(
      { type: 'subscription.revoked', data: { product: {}, customer: { email: 'b@example.com' } } },
      {
        appMeta: { plan: 'pro', paid: true, paid_since: '2026-01-01', comp_until: '2026-03-31' },
        env: { RESEND_API_KEY: 're_test', NOTIFY_FROM: 'n@baklog.app', NOTIFY_TO: 'f@example.com' },
      },
    );
    const mail = fetchMock.mock.calls.find(([u]) => String(u) === 'https://api.resend.com/emails');
    for (const k of ['RESEND_API_KEY', 'NOTIFY_FROM', 'NOTIFY_TO']) delete process.env[k];
    expect(mail).toBeTruthy();
    const text = JSON.parse(mail[1].body).text;
    expect(text).toContain('Event: subscription.revoked');
    expect(text).toContain('Credited 89 unused beta day(s)');
  });

  async function postUnmatched(event, { pendingOk = true } = {}) {
    vi.resetModules();
    process.env.POLAR_WEBHOOK_SECRET = WEBHOOK_SECRET;
    process.env.SUPABASE_URL = SUPABASE_URL;
    process.env.SUPABASE_SERVICE_ROLE_KEY = SERVICE_KEY;
    process.env.RESEND_API_KEY = 're_test';
    process.env.NOTIFY_FROM = 'BAKLOG <n@baklog.app>';
    process.env.NOTIFY_TO = 'founder@example.com';
    const body = JSON.stringify(event);
    const sig = signBody(body);
    const fetchMock = vi.fn(async (url) => {
      const u = String(url);
      if (u.includes('/rpc/get_user_id_by_email')) {
        return { ok: true, json: async () => null };
      }
      if (u.includes('/rest/v1/polar_pending_entitlements')) {
        return pendingOk
          ? { ok: true, text: async () => '' }
          : { ok: false, status: 500, text: async () => 'db down' };
      }
      if (u === 'https://api.resend.com/emails') {
        return { ok: true, text: async () => '' };
      }
      throw new Error(`unexpected fetch ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    const mod = await import('../web/api/polar-webhook.js');
    const res = await mod.default.fetch(new Request('https://baklog.app/api/polar-webhook', {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'webhook-id': sig.id,
        'webhook-timestamp': sig.timestamp,
        'webhook-signature': sig.signature,
      },
      body,
    }));
    const json = await res.json();
    for (const k of ['RESEND_API_KEY', 'NOTIFY_FROM', 'NOTIFY_TO']) delete process.env[k];
    return { res, json, fetchMock };
  }

  const callTo = (fetchMock, fragment) =>
    fetchMock.mock.calls.find(([url]) => String(url).includes(fragment));

  it('stores unmatched buyers as pending and alerts the founder', async () => {
    const { res, json, fetchMock } = await postUnmatched({
      type: 'order.paid',
      data: {
        product: {},
        customer_id: 'cus_1',
        subscription_id: 'sub_1',
        customer: { email: 'Unknown@Example.com' },
      },
    });
    expect(res.status).toBe(202);
    expect(json).toMatchObject({ ok: true, matched: false, pending: true });
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/auth/v1/admin/users/'))).toBe(false);
    const [, upsertInit] = callTo(fetchMock, '/rest/v1/polar_pending_entitlements');
    expect(upsertInit.method).toBe('POST');
    const row = JSON.parse(upsertInit.body);
    expect(row).toMatchObject({
      email: 'unknown@example.com',
      plan: 'pro',
      last_event_type: 'order.paid',
      polar_customer_id: 'cus_1',
      polar_subscription_id: 'sub_1',
    });
    const [, mailInit] = callTo(fetchMock, 'api.resend.com');
    const mail = JSON.parse(mailInit.body);
    expect(mail.subject).toContain('Unmatched Polar buyer: unknown@example.com');
    expect(mail.text).toContain('applies automatically');
  });

  it('flips a pending unmatched buyer to free on revoke', async () => {
    const { res, fetchMock } = await postUnmatched({
      type: 'subscription.revoked',
      data: { id: 'sub_9', product: {}, customer: { email: 'gone@example.com' } },
    });
    expect(res.status).toBe(202);
    const row = JSON.parse(callTo(fetchMock, '/rest/v1/polar_pending_entitlements')[1].body);
    expect(row).toMatchObject({ email: 'gone@example.com', plan: 'free', polar_subscription_id: 'sub_9' });
  });

  it('returns 500 so Polar retries when the pending store fails', async () => {
    const { res, fetchMock } = await postUnmatched(
      { type: 'order.paid', data: { product: {}, customer: { email: 'x@example.com' } } },
      { pendingOk: false },
    );
    expect(res.status).toBe(500);
    expect(callTo(fetchMock, 'api.resend.com')).toBeUndefined();
  });

  it('alerts without storing when the unmatched event has no email', async () => {
    const { res, json, fetchMock } = await postUnmatched({
      type: 'order.paid',
      data: { product: {}, customer: {} },
    });
    expect(res.status).toBe(202);
    expect(json.pending).toBe(false);
    expect(callTo(fetchMock, '/rest/v1/polar_pending_entitlements')).toBeUndefined();
    expect(JSON.parse(callTo(fetchMock, 'api.resend.com')[1].body).text).toContain('Not saved');
  });

  describe('subscription.updated status mapping', () => {
    const updated = (status) => ({
      type: 'subscription.updated',
      data: { status, product: { metadata: { plan: 'pro' } }, customer: { email: 'b@example.com' } },
    });
    const puts = (fetchMock) =>
      fetchMock.mock.calls.filter(([, init]) => String(init?.method || '').toUpperCase() === 'PUT');

    it('keeps Pro on active (including a scheduled cancel)', async () => {
      const { res, json, fetchMock } = await postWebhook({
        ...updated('active'),
        data: { ...updated('active').data, cancel_at_period_end: true },
      });
      expect(res.status).toBe(202);
      expect(json.plan).toBe('pro');
      expect(putMeta(fetchMock)).toMatchObject({ plan: 'pro', paid: true });
    });

    for (const status of ['trialing', 'past_due', undefined]) {
      it(`leaves the plan unchanged on ${status ?? 'missing status'}`, async () => {
        const { res, json, fetchMock } = await postWebhook(updated(status), {
          appMeta: { plan: 'pro', paid: true, paid_since: '2026-01-01' },
        });
        expect(res.status).toBe(202);
        expect(json.ignored).toBe('subscription.updated');
        expect(puts(fetchMock)).toHaveLength(0);
      });
    }

    for (const status of ['canceled', 'unpaid', 'paused', 'incomplete', 'incomplete_expired']) {
      it(`drops to free on ${status}`, async () => {
        const { res, json, fetchMock } = await postWebhook(updated(status), {
          appMeta: { plan: 'pro', paid: true, paid_since: '2026-01-01' },
        });
        expect(res.status).toBe(202);
        expect(json.plan).toBe('free');
        expect(putMeta(fetchMock)).toMatchObject({ plan: 'free', paid: null });
      });
    }
  });

  it('applies a Polar retry with the same event time once (one PUT, one email)', async () => {
    vi.resetModules();
    process.env.POLAR_WEBHOOK_SECRET = WEBHOOK_SECRET;
    process.env.SUPABASE_URL = SUPABASE_URL;
    process.env.SUPABASE_SERVICE_ROLE_KEY = SERVICE_KEY;
    Object.assign(process.env, { RESEND_API_KEY: 're_test', NOTIFY_FROM: 'n@baklog.app', NOTIFY_TO: 'f@example.com' });
    let stored = { beta: true };
    const fetchMock = vi.fn(async (url, init) => {
      const u = String(url);
      const method = (init?.method || 'GET').toUpperCase();
      if (u.includes('/rpc/get_user_id_by_email')) {
        return { ok: true, json: async () => '11111111-1111-4111-8111-111111111111' };
      }
      if (u.includes('/auth/v1/admin/users/')) {
        if (method === 'GET') {
          return {
            ok: true,
            json: async () => ({ email: 'b@example.com', email_confirmed_at: CONFIRMED_AT, app_metadata: { ...stored } }),
          };
        }
        stored = { ...stored, ...JSON.parse(init.body).app_metadata };
        return { ok: true, json: async () => ({}) };
      }
      if (u === 'https://api.resend.com/emails') return { ok: true, text: async () => '' };
      throw new Error(`unexpected fetch ${u}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    const mod = await import('../web/api/polar-webhook.js');
    const body = JSON.stringify({
      type: 'order.paid',
      data: { created_at: '2026-10-10T00:00:00Z', product: {}, customer: { email: 'b@example.com' } },
    });
    const send = () => {
      const sig = signBody(body);
      return mod.default.fetch(new Request('https://baklog.app/api/polar-webhook', {
        method: 'POST',
        headers: {
          'content-type': 'application/json',
          'webhook-id': sig.id,
          'webhook-timestamp': sig.timestamp,
          'webhook-signature': sig.signature,
        },
        body,
      }));
    };
    const first = await (await send()).json();
    const retry = await (await send()).json();
    for (const k of ['RESEND_API_KEY', 'NOTIFY_FROM', 'NOTIFY_TO']) delete process.env[k];
    expect(first.plan).toBe('pro');
    expect(retry.stale).toBe(true);
    const putCalls = fetchMock.mock.calls.filter(([, init]) => String(init?.method || '').toUpperCase() === 'PUT');
    expect(putCalls).toHaveLength(1);
    const mails = fetchMock.mock.calls.filter(([u]) => String(u) === 'https://api.resend.com/emails');
    expect(mails).toHaveLength(1);
  });

  it('routes an external_id match with an unconfirmed email to pending', async () => {
    const userId = '22222222-2222-4222-8222-222222222222';
    const { res, json, fetchMock } = await postWebhook(
      { type: 'order.paid', data: { product: {}, customer: { external_id: userId, email: 'new@example.com' } } },
      { confirmedAt: null },
    );
    expect(res.status).toBe(202);
    expect(json).toMatchObject({ matched: false, pending: true });
    expect(fetchMock.mock.calls.some(([, init]) => String(init?.method || '').toUpperCase() === 'PUT')).toBe(false);
    expect(fetchMock.mock.calls.some(([u]) => String(u).includes('/rpc/get_user_id_by_email'))).toBe(false);
    const upsert = fetchMock.mock.calls.find(([u]) => String(u).includes('/rest/v1/polar_pending_entitlements'));
    expect(JSON.parse(upsert[1].body)).toMatchObject({ email: 'new@example.com', plan: 'pro' });
  });

  it('rejects an oversized Content-Length before reading the body', async () => {
    vi.resetModules();
    process.env.POLAR_WEBHOOK_SECRET = WEBHOOK_SECRET;
    process.env.SUPABASE_URL = SUPABASE_URL;
    process.env.SUPABASE_SERVICE_ROLE_KEY = SERVICE_KEY;
    const mod = await import('../web/api/polar-webhook.js');
    const text = vi.fn(async () => '{}');
    const res = await mod.default.fetch({
      method: 'POST',
      headers: new Headers({ 'content-length': String(1024 * 1024 + 1) }),
      text,
    });
    expect(res.status).toBe(413);
    expect(text).not.toHaveBeenCalled();
  });

  it('accepts whsec_ prefixed signing secrets', async () => {
    const whsecBody = JSON.stringify({
      type: 'subscription.active',
      data: {
        product: { metadata: { plan: 'pro' } },
        customer: { email: 'buyer@example.com' },
      },
    });
    const id = 'msg_whsec_1';
    const timestamp = String(Math.floor(Date.now() / 1000));
    const rawSecret = 'polar_test_secret';
    const keyBytes = Buffer.from(rawSecret, 'utf8');
    const mac = createHmac('sha256', keyBytes).update(`${id}.${timestamp}.${whsecBody}`).digest('base64');
    vi.resetModules();
    process.env.POLAR_WEBHOOK_SECRET = `whsec_${Buffer.from(rawSecret).toString('base64')}`;
    process.env.SUPABASE_URL = SUPABASE_URL;
    process.env.SUPABASE_SERVICE_ROLE_KEY = SERVICE_KEY;
    const fetchMock = vi.fn(async (url) => {
      if (String(url).includes('/rpc/get_user_id_by_email')) {
        return { ok: true, json: async () => '11111111-1111-4111-8111-111111111111' };
      }
      if (String(url).includes('/auth/v1/admin/users/')) {
        return { ok: true, json: async () => ({ email_confirmed_at: CONFIRMED_AT }) };
      }
      throw new Error(`unexpected fetch ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    const mod = await import('../web/api/polar-webhook.js');
    const res = await mod.default.fetch(new Request('https://baklog.app/api/polar-webhook', {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'webhook-id': id,
        'webhook-timestamp': timestamp,
        'webhook-signature': `v1,${mac}`,
      },
      body: whsecBody,
    }));
    expect(res.status).toBe(202);
  });
});
