import { queryGames } from './table-query.js';

self.onmessage = (ev) => {
  const { id, payload } = ev.data || {};
  const source = payload.source || [];
  const ctx = payload.ctx || {};
  ctx.hiddenKeys = new Set(ctx.hiddenKeys || []);
  ctx.ownedNormNames = new Set(ctx.ownedNormNames || []);
  ctx.combinedPlaytime = new Map(ctx.combinedPlaytime || []);
  ctx.playedTitleNorms = new Set(ctx.playedTitleNorms || []);
  // Prefer indices from the filter pass (O(n)) — avoid source.indexOf remap.
  const result = queryGames({ source, ctx, returnIndices: true });
  self.postMessage({ id, indices: result.indices });
};
