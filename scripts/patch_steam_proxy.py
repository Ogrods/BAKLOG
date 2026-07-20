"""Minimal patch: change steamSearch and steamAppReviews to use local proxy."""
path = "js/add-game-modal.js"
content = open(path, encoding="utf-8").read()

old1 = '''async function steamSearch(term) {
  const url = `https://store.steampowered.com/api/storesearch/?term=${encodeURIComponent(term)}&l=english&cc=US`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Steam search HTTP ${res.status}`);
  const data = await res.json();
  return (data.items || []).slice(0, 6);
}'''

new1 = '''async function steamSearch(term) {
  const res = await fetch(`/api/proxy/steam-search?term=${encodeURIComponent(term)}`);
  if (!res.ok) throw new Error(`Steam search HTTP ${res.status}`);
  const data = await res.json();
  return (data.items || []).slice(0, 6);
}'''

old2 = '''async function steamAppReviews(appid) {
  const url = `https://store.steampowered.com/appreviews/${appid}?json=1&language=all&purchase_type=all&num_per_page=0`;
  try {
    const res = await fetch(url);
    if (!res.ok) return null;
    const data = await res.json();
    if (!data.success || !data.query_summary) return null;
    const q = data.query_summary;
    return {
      steam_review_percent: q.total_reviews > 0 ? Math.round((q.total_positive / q.total_reviews) * 100) : null,
      steam_review_count: q.total_reviews || 0,
      steam_review_desc: q.review_score_desc || null,
    };
  } catch { return null; }
}'''

new2 = '''async function steamAppReviews(appid) {
  try {
    const res = await fetch(`/api/proxy/steam-reviews?appid=${appid}`);
    if (!res.ok) return null;
    const data = await res.json();
    if (!data.success || !data.query_summary) return null;
    const q = data.query_summary;
    return {
      steam_review_percent: q.total_reviews > 0 ? Math.round((q.total_positive / q.total_reviews) * 100) : null,
      steam_review_count: q.total_reviews || 0,
      steam_review_desc: q.review_score_desc || null,
    };
  } catch { return null; }
}'''

assert old1 in content, "FAIL: steamSearch not found in source"
assert old2 in content, "FAIL: steamAppReviews not found in source"

content = content.replace(old1, new1).replace(old2, new2)

open(path, "w", encoding="utf-8").write(content)
print("OK")
print(f"steamSearch changed: {old1 not in content}")
print(f"steamAppReviews changed: {old2 not in content}")
