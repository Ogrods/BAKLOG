/**
 * Display currency — derived from ITAD fetch country/currency in state.libraryMeta.itad.
 */

import { state } from './state.js';

const COUNTRY_CURRENCY = {
  US: 'USD',
  GB: 'GBP',
  UK: 'GBP',
  CA: 'CAD',
  AU: 'AUD',
  NZ: 'NZD',
  JP: 'JPY',
  KR: 'KRW',
  CN: 'CNY',
  IN: 'INR',
  BR: 'BRL',
  MX: 'MXN',
  NO: 'NOK',
  SE: 'SEK',
  DK: 'DKK',
  PL: 'PLN',
  CH: 'CHF',
  RU: 'RUB',
  TR: 'TRY',
  ZA: 'ZAR',
  DE: 'EUR',
  FR: 'EUR',
  IT: 'EUR',
  ES: 'EUR',
  NL: 'EUR',
  BE: 'EUR',
  AT: 'EUR',
  IE: 'EUR',
  PT: 'EUR',
  FI: 'EUR',
  GR: 'EUR',
};

const STEAM_CURRENCY = {
  usd: 'USD',
  eur: 'EUR',
  gbp: 'GBP',
  cad: 'CAD',
  aud: 'AUD',
  nzd: 'NZD',
  jpy: 'JPY',
  krw: 'KRW',
  cny: 'CNY',
  inr: 'INR',
  brl: 'BRL',
  mxn: 'MXN',
  nok: 'NOK',
  sek: 'SEK',
  dkk: 'DKK',
  pln: 'PLN',
  chf: 'CHF',
  rub: 'RUB',
  try: 'TRY',
  zar: 'ZAR',
};

export function countryToCurrency(country) {
  if (!country) return 'USD';
  const key = String(country).trim().toUpperCase();
  return COUNTRY_CURRENCY[key] || 'USD';
}

export function normalizeCurrencyCode(code, country) {
  if (code) {
    const raw = String(code).trim();
    const steam = STEAM_CURRENCY[raw.toLowerCase()];
    if (steam) return steam;
    if (/^[A-Za-z]{3}$/.test(raw)) return raw.toUpperCase();
  }
  if (country) return countryToCurrency(country);
  return 'USD';
}

/** ISO 4217 code used for ITAD-backed deal display and dashboard totals. */
export function displayCurrency() {
  const meta = state.libraryMeta?.itad;
  if (meta?.currency) return normalizeCurrencyCode(meta.currency);
  if (meta?.country) return countryToCurrency(meta.country);
  return 'USD';
}

/**
 * Format a numeric amount in the given currency (defaults to displayCurrency()).
 * @param {number | null | undefined} amount
 * @param {string | null | undefined} [code]
 * @param {{ maximumFractionDigits?: number, minimumFractionDigits?: number }} [opts]
 */
export function formatMoney(amount, code, opts = {}) {
  if (amount == null || amount === '') return '—';
  const num = Number(amount);
  if (!Number.isFinite(num)) return '—';
  const cur = normalizeCurrencyCode(code || displayCurrency());
  const fracDigits = opts.maximumFractionDigits ?? (cur === 'JPY' || cur === 'KRW' ? 0 : 2);
  try {
    return new Intl.NumberFormat(undefined, {
      style: 'currency',
      currency: cur,
      minimumFractionDigits: opts.minimumFractionDigits ?? (fracDigits === 0 ? 0 : (num % 1 ? 2 : 0)),
      maximumFractionDigits: fracDigits,
    }).format(num);
  } catch {
    return `${cur} ${num.toFixed(2)}`;
  }
}

/** Small tag when a row's store currency differs from the ITAD display currency. */
export function currencyMismatchTag(code) {
  const rowCur = normalizeCurrencyCode(code);
  const disp = displayCurrency();
  if (!code || rowCur === disp) return '';
  return `<span class="price-currency-tag" title="Store price in ${rowCur}">${rowCur}</span>`;
}
