/**
 * Tests for js/currency.js — display currency from ITAD meta + formatting.
 */

import { describe, expect, it, beforeEach } from 'vitest';
import { state } from '../js/state.js';
import {
  countryToCurrency,
  normalizeCurrencyCode,
  displayCurrency,
  formatMoney,
  currencyMismatchTag,
  currencyMismatchTagForGame,
} from '../js/currency.js';

beforeEach(() => {
  state.libraryMeta = { itad: null };
});

describe('countryToCurrency', () => {
  it('maps common storefront countries', () => {
    expect(countryToCurrency('US')).toBe('USD');
    expect(countryToCurrency('GB')).toBe('GBP');
    expect(countryToCurrency('DE')).toBe('EUR');
    expect(countryToCurrency('bogus')).toBe('USD');
  });
});

describe('normalizeCurrencyCode', () => {
  it('normalizes Steam-style codes', () => {
    expect(normalizeCurrencyCode('eur')).toBe('EUR');
    expect(normalizeCurrencyCode('gbp')).toBe('GBP');
  });
});

describe('displayCurrency', () => {
  it('prefers itad.currency then country then USD', () => {
    state.libraryMeta.itad = { currency: 'GBP', country: 'US' };
    expect(displayCurrency()).toBe('GBP');
    state.libraryMeta.itad = { country: 'DE' };
    expect(displayCurrency()).toBe('EUR');
    state.libraryMeta.itad = null;
    expect(displayCurrency()).toBe('USD');
  });
});

describe('formatMoney', () => {
  it('formats USD and EUR', () => {
    expect(formatMoney(9.99, 'USD')).toMatch(/\$9\.99/);
    const eur = formatMoney(12.5, 'EUR');
    expect(eur).toMatch(/12/);
    expect(eur).toMatch(/50|5/);
  });

  it('returns placeholder for non-finite amounts', () => {
    expect(formatMoney(null, 'USD')).toBe(' - ');
  });
});

describe('currencyMismatchTag', () => {
  it('tags when row currency differs from display', () => {
    state.libraryMeta.itad = { currency: 'USD', country: 'US' };
    expect(currencyMismatchTag('EUR')).toContain('EUR');
    expect(currencyMismatchTag('USD')).toBe('');
  });
});

describe('currencyMismatchTagForGame', () => {
  it('shows native currency after FX conversion', () => {
    state.libraryMeta.itad = { currency: 'USD', country: 'US' };
    const tag = currencyMismatchTagForGame({
      currency: 'USD',
      currency_native: 'GBP',
      price_native: '£45.00',
    });
    expect(tag).toContain('GBP');
    expect(tag).toContain('£45.00');
  });
});
