import { describe, expect, it } from 'vitest';
import { applyPaidEntitlement, compActive } from '../web/api/_polar-pending.js';

const at = (day) => new Date(`${day}T12:00:00Z`);

describe('applyPaidEntitlement', () => {
  it('stamps paid_since on the first paid event only', () => {
    const first = applyPaidEntitlement({ plan: 'pro', comp_until: '2027-03-31' }, 'pro', { now: at('2027-01-01') });
    expect(first.meta).toMatchObject({ plan: 'pro', paid: true, paid_since: '2027-01-01' });
    const renewal = applyPaidEntitlement(first.meta, 'pro', { now: at('2027-02-01') });
    expect(renewal.meta.paid_since).toBe('2027-01-01');
  });

  it('credits unused beta days when a mid-beta payer cancels after the beta', () => {
    const meta = { plan: 'pro', paid: true, paid_since: '2027-01-01', comp_until: '2027-03-31' };
    const out = applyPaidEntitlement(meta, 'free', { now: at('2027-06-01') });
    expect(out.creditedDays).toBe(89);
    expect(out.meta).toEqual({ plan: 'pro', comp_until: '2027-08-29' });
  });

  it('credits from the cancel date when cancelling during the beta', () => {
    const meta = { plan: 'pro', paid: true, paid_since: '2027-01-01', comp_until: '2027-03-31' };
    const out = applyPaidEntitlement(meta, 'free', { now: at('2027-02-01') });
    expect(out.meta).toEqual({ plan: 'pro', comp_until: '2027-05-01' });
  });

  it('gives no credit when payment started after the beta ended', () => {
    const meta = { plan: 'pro', paid: true, paid_since: '2027-05-01', comp_until: '2027-03-31' };
    const out = applyPaidEntitlement(meta, 'free', { now: at('2027-07-01') });
    expect(out.creditedDays).toBe(0);
    expect(out.meta).toEqual({ plan: 'free', comp_until: '2027-03-31' });
  });

  it('never double-counts across pay, cancel, pay, cancel', () => {
    let meta = { plan: 'pro', comp_until: '2027-03-31' };
    meta = applyPaidEntitlement(meta, 'pro', { now: at('2027-01-01') }).meta;
    meta = applyPaidEntitlement(meta, 'free', { now: at('2027-02-01') }).meta;
    expect(meta.comp_until).toBe('2027-05-01');
    meta = applyPaidEntitlement(meta, 'pro', { now: at('2027-02-15') }).meta;
    meta = applyPaidEntitlement(meta, 'free', { now: at('2027-03-01') }).meta;
    expect(meta).toEqual({ plan: 'pro', comp_until: '2027-05-15' });
  });

  it('drops to free on cancel for a payer with no comp', () => {
    const out = applyPaidEntitlement({ plan: 'pro', paid: true, paid_since: '2027-01-01' }, 'free', { now: at('2027-02-01') });
    expect(out.meta).toEqual({ plan: 'free' });
  });

  it('treats older events as stale and records the newest event time', () => {
    const fresh = applyPaidEntitlement({}, 'free', { eventAt: '2027-01-02T00:00:00Z', now: at('2027-01-02') });
    expect(fresh.meta.polar_event_at).toBe('2027-01-02T00:00:00.000Z');
    const old = applyPaidEntitlement(fresh.meta, 'pro', { eventAt: '2027-01-01T00:00:00Z', now: at('2027-01-03') });
    expect(old.stale).toBe(true);
    expect(old.meta).toEqual(fresh.meta);
  });

  it('compActive covers comp_until through the end of that day', () => {
    expect(compActive({ comp_until: '2027-03-31' }, at('2027-03-31'))).toBe(true);
    expect(compActive({ comp_until: '2027-03-31' }, at('2027-04-01'))).toBe(false);
    expect(compActive({}, at('2027-04-01'))).toBe(false);
  });
});
