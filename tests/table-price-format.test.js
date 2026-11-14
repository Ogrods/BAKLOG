import { beforeEach, describe, expect, it, vi } from 'vitest';

describe('formatPrice deal href gate', () => {
  beforeEach(() => {
    vi.resetModules();
  });

  it('renders https deal links and skips javascript: urls', async () => {
    vi.doMock('../js/deals.js', () => ({
      cutBucketClass: () => 'cut-hi',
      dealDroppedBadgeHtml: () => '',
      getDealInfo: () => null,
      getItadForGame: () => ({
        price: 9.99,
        cut: 50,
        currency: 'USD',
        shop: 'Steam',
        url: 'javascript:alert(1)',
      }),
      priceLowStarHtml: () => '',
    }));
    vi.doMock('../js/currency.js', () => ({
      formatMoney: (n) => `$${n}`,
      currencyMismatchTagForGame: () => '',
      displayCurrency: () => 'USD',
    }));
    const { formatPrice } = await import('../js/table-price-format.js');
    const bad = formatPrice({ id: 1 });
    expect(bad).not.toContain('<a ');
    expect(bad).toContain('$9.99');

    vi.resetModules();
    vi.doMock('../js/deals.js', () => ({
      cutBucketClass: () => 'cut-hi',
      dealDroppedBadgeHtml: () => '',
      getDealInfo: () => null,
      getItadForGame: () => ({
        price: 4.99,
        cut: 10,
        currency: 'USD',
        shop: 'Steam',
        url: 'https://isthereanydeal.com/game/x/info/',
      }),
      priceLowStarHtml: () => '',
    }));
    vi.doMock('../js/currency.js', () => ({
      formatMoney: (n) => `$${n}`,
      currencyMismatchTagForGame: () => '',
      displayCurrency: () => 'USD',
    }));
    const { formatPrice: formatPriceOk } = await import('../js/table-price-format.js');
    const good = formatPriceOk({ id: 2 });
    expect(good).toContain('<a href="https://isthereanydeal.com/game/x/info/"');
  });
});
