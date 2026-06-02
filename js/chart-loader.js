/**
 * Load Chart.js on demand so library/wishlist/itch cold boot skips ~200KB parse.
 */

let _loadPromise = null;

export function chartJsReady() {
  return typeof Chart !== 'undefined';
}

export function ensureChartJs() {
  if (chartJsReady()) return Promise.resolve();
  if (_loadPromise) return _loadPromise;
  _loadPromise = new Promise((resolve, reject) => {
    const existing = document.querySelector('script[data-baklog-chart]');
    if (existing) {
      if (existing.dataset.loaded === '1') {
        resolve();
        return;
      }
      existing.addEventListener('load', () => resolve(), { once: true });
      existing.addEventListener('error', () => reject(new Error('Chart.js failed to load')), { once: true });
      return;
    }
    const s = document.createElement('script');
    s.src = 'vendor/chart.umd.min.js';
    s.async = true;
    s.dataset.baklogChart = '1';
    s.addEventListener('load', () => {
      s.dataset.loaded = '1';
      resolve();
    }, { once: true });
    s.addEventListener('error', () => {
      _loadPromise = null;
      reject(new Error('Chart.js failed to load'));
    }, { once: true });
    document.head.appendChild(s);
  });
  return _loadPromise;
}
