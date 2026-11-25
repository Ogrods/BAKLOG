/**
 * Fixed enricher run order. steamReviews builds the appid map that
 * steamTags / steamCovers consume - do not reorder those three.
 */
export const ENRICH_ORDER = ['steamReviews', 'steamTags', 'steamCovers', 'protondb', 'hltb'];
