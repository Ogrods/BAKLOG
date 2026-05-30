import { queryGames } from './table-query.js';

self.onmessage = (ev) => {
  const { id, payload } = ev.data || {};
  const source = payload.source || [];
  const ctx = payload.ctx || {};
  ctx.hiddenKeys = new Set(ctx.hiddenKeys || []);
  ctx.ownedNormNames = new Set(ctx.ownedNormNames || []);
  const list = queryGames({ source, ctx });
  const indices = list.map(g => source.indexOf(g));
  self.postMessage({ id, indices });
};
