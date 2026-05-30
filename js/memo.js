/** Tiny LRU-ish memo for hot per-game lookups. */

export function createMemo(maxSize = 8000) {
  const cache = new Map();
  let generation = 0;

  return {
    bump() {
      generation += 1;
      cache.clear();
    },
    get(key, compute) {
      const k = `${generation}:${key}`;
      if (cache.has(k)) return cache.get(k);
      const val = compute();
      if (cache.size >= maxSize) cache.clear();
      cache.set(k, val);
      return val;
    },
  };
}
