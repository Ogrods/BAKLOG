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

async function postWebhook(event, { secret = WEBHOOK_SECRET, env = {} } = {}) {
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
      return { ok: true, json: async () => ({}) };
    }
    throw new Error(`unexpected fetch ${url} ${init?.method || ''}`);
  });
  vi.stubGlobal('fetch', fetchMock);
  const mod = await import('../landing/api/polar-webhook.js');
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
    const mod = await import('../landing/api/polar-webhook.js');
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
});
