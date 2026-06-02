/**
 * Games pre-hidden on first run (formerly Python fetcher denylists).
 * Users can restore any entry from the Hidden games panel.
 */
export const PRE_HIDDEN_KEYS = [
  { key: 'epic:4b5f1eb366dc45f0920d397c01b291ba:8d644d777e5042c187c03530b965dc17', name: 'Q.U.B.E. 2 — Glove Skin', store: 'epic' },
  { key: 'epic:4b5f1eb366dc45f0920d397c01b291ba:ade772fcce3a41cf97279032c10b0041', name: 'Q.U.B.E. 2 — Puzzle Pack 1', store: 'epic' },
  { key: 'epic:4b5f1eb366dc45f0920d397c01b291ba:b36ab3b81c844ee2a908c7d28451337a', name: 'Q.U.B.E. 2 — Puzzle Pack 2', store: 'epic' },
  { key: 'epic:4b5f1eb366dc45f0920d397c01b291ba:8c8ee5e50c7c42a7b59a9ee8c31c0330', name: 'Q.U.B.E. 2 Soundtrack', store: 'epic' },
  { key: 'epic:7015c51a49be4592b5ba3ae2577723c5:ca31f80025ea4466b871ba11184bc74b', name: 'Map Pack (DLC)', store: 'epic' },
  { key: 'epic:f4a904fcef2447439c35c4e6457f3027:678578f8abe84265b0d5f81c1997c6da', name: 'Death Stranding Content (DLC bundle)', store: 'epic' },
  { key: 'epic:f4a904fcef2447439c35c4e6457f3027:c7bad4fcef1e4188b36732ed4bdf8103', name: 'Death Stranding Digital Soundtrack', store: 'epic' },
  { key: 'epic:f4a904fcef2447439c35c4e6457f3027:01ced6494f3046e48b9bbb7d2874b703', name: 'Death Stranding — HD Wallpaper', store: 'epic' },
  { key: 'psn:CUSA20387_00', name: 'PeacockTV', store: 'psn' },
  { key: 'psn:PPSA06399_00', name: 'PAC-MAN WORLD Re-PAC Chrome Noir Chogokin skin', store: 'psn' },
  { key: 'psn:CUSA03390_00', name: 'NFL app', store: 'psn' },
  { key: 'psn:CUSA06566_00', name: 'NBA app', store: 'psn' },
  { key: 'psn:CUSA02012_00', name: 'Media Player', store: 'psn' },
  { key: 'psn:CUSA18774_00', name: '4 YoRHa (NieR demo chapter)', store: 'psn' },
];

/** @type {Map<string, { name: string, store: string }>} */
export const PRE_HIDDEN_BY_KEY = new Map(PRE_HIDDEN_KEYS.map(e => [e.key, { name: e.name, store: e.store }]));

export function getPreHiddenFallback(key) {
  return PRE_HIDDEN_BY_KEY.get(key) || null;
}
