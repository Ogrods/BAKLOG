/* @vitest-environment node */
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import authConfigHandler from '../landing/api/auth-config.js';

const { fetch: handleAuthConfig } = authConfigHandler;

const ENV_KEYS = [
  'BAKLOG_SUPABASE_URL',
  'BAKLOG_SUPABASE_ANON_KEY',
  'SUPABASE_URL',
  'SUPABASE_ANON_KEY',
  'VERCEL_ENV',
  'KV_REST_API_URL',
  'KV_REST_API_TOKEN',
  'UPSTASH_REDIS_REST_URL',
  'UPSTASH_REDIS_REST_TOKEN',
];

function makeRequest({ ip = '10.0.0.1', method = 'GET' } = {}) {
  return new Request('https://baklog.app/api/auth-config', {
    method,
    headers: { 'x-forwarded-for': ip },
  });
}

describe('landing/api/auth-config.js', () => {
  beforeEach(() => {
    delete process.env.BAKLOG_SUPABASE_URL;
    delete process.env.BAKLOG_SUPABASE_ANON_KEY;
    delete process.env.SUPABASE_URL;
    delete process.env.SUPABASE_ANON_KEY;
    delete process.env.VERCEL_ENV;
    delete process.env.KV_REST_API_URL;
    delete process.env.KV_REST_API_TOKEN;
    delete process.env.UPSTASH_REDIS_REST_URL;
    delete process.env.UPSTASH_REDIS_REST_TOKEN;
  });

  afterEach(() => {
    for (const key of ENV_KEYS) delete process.env[key];
  });

  it('returns 503 when env is missing', async () => {
    const res = await handleAuthConfig(makeRequest());
    expect(res.status).toBe(503);
  });

  it('returns public config from BAKLOG_* env', async () => {
    process.env.BAKLOG_SUPABASE_URL = 'https://demo.supabase.co';
    process.env.BAKLOG_SUPABASE_ANON_KEY = 'public-anon-key';
    const res = await handleAuthConfig(makeRequest());
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body).toEqual({
      supabaseUrl: 'https://demo.supabase.co',
      supabaseAnonKey: 'public-anon-key',
    });
  });

  it('falls back to SUPABASE_URL env names', async () => {
    process.env.SUPABASE_URL = 'https://fallback.supabase.co';
    process.env.SUPABASE_ANON_KEY = 'fallback-anon';
    const res = await handleAuthConfig(makeRequest());
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.supabaseUrl).toBe('https://fallback.supabase.co');
    expect(body.supabaseAnonKey).toBe('fallback-anon');
  });

  it('rejects non-GET', async () => {
    process.env.BAKLOG_SUPABASE_URL = 'https://demo.supabase.co';
    process.env.BAKLOG_SUPABASE_ANON_KEY = 'anon';
    const res = await handleAuthConfig(makeRequest({ method: 'POST' }));
    expect(res.status).toBe(405);
  });

  it('rate limits more than five requests per IP per minute', async () => {
    process.env.BAKLOG_SUPABASE_URL = 'https://demo.supabase.co';
    process.env.BAKLOG_SUPABASE_ANON_KEY = 'anon';
    const ip = '192.168.2.99';
    for (let i = 0; i < 5; i += 1) {
      const res = await handleAuthConfig(makeRequest({ ip }));
      expect(res.status).toBe(200);
    }
    const blocked = await handleAuthConfig(makeRequest({ ip }));
    expect(blocked.status).toBe(429);
    expect(await blocked.json()).toEqual({ error: 'Too many requests' });
  });

  it('returns 503 in production when KV credentials are missing', async () => {
    process.env.VERCEL_ENV = 'production';
    process.env.BAKLOG_SUPABASE_URL = 'https://demo.supabase.co';
    process.env.BAKLOG_SUPABASE_ANON_KEY = 'anon';
    const res = await handleAuthConfig(makeRequest());
    expect(res.status).toBe(503);
    expect(await res.json()).toEqual({ error: 'Server not configured' });
  });
});
