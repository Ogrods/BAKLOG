"""Cross-source dupe grouping for the free-claims inbox.

Groups rows that describe the same giveaway (Epic API + GamerPower + ITAD
copies) so admin can show "Dupe xN" and the build/autopilot can keep one
winner per group.

- **strong** groups come from shared ``claim_match_keys`` (appid / normalized
  title, ``:mobile``-suffixed) plus the Epic store slug. Safe to auto-merge.
- **possible** groups link strong components whose edition-stripped titles
  match ("X Deluxe" vs "X") or whose appid matches across a spin-off title.
  Never auto-merged; admin review only.

``dupe_splits`` (owner "not a dupe" decisions) are id pairs whose edges are
ignored, so a false positive can be overridden without code changes.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from shared.free_claims_sources import (
    SOURCE_PRECEDENCE,
    claim_match_keys,
    is_epic_mobile_store,
    norm_title,
)
from shared.steam_match import _SPINOFF_MARKERS, normalize_title

MERGE_FIELDS = ("ends_at", "steam_appid", "header_image")

_EPIC_SLUG_RE = re.compile(r"store\.epicgames\.com/(?:[a-z]{2}(?:-[A-Z]{2})?/)?p/([a-z0-9-]+)", re.I)
_EPIC_HASH_SUFFIX_RE = re.compile(r"-[0-9a-f]{6}$")


@dataclass
class ClaimGroup:
    key: str
    winner_id: str
    member_ids: list[str]
    tier: str  # "strong" | "possible"
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "winner_id": self.winner_id,
            "member_ids": list(self.member_ids),
            "tier": self.tier,
            "reasons": list(self.reasons),
            "size": len(self.member_ids),
        }


def _suffix(item: dict) -> str:
    return ":mobile" if is_epic_mobile_store(item.get("store")) else ""


def epic_slug_key(item: dict) -> str | None:
    """``epic:<slug>`` from any Epic store URL on the row (hash suffix dropped)."""
    for url in (item.get("claim_url"), item.get("open_giveaway_url")):
        m = _EPIC_SLUG_RE.search(str(url or ""))
        if m:
            slug = _EPIC_HASH_SUFFIX_RE.sub("", m.group(1).lower())
            if slug:
                return f"epic:{slug}{_suffix(item)}"
    return None


def strong_keys(item: dict) -> set[str]:
    keys = set(claim_match_keys(item))
    slug = epic_slug_key(item)
    if slug:
        keys.add(slug)
    return keys


def weak_key(item: dict) -> str | None:
    """Edition-stripped title key ("X Deluxe Edition" -> "x")."""
    stripped = normalize_title(norm_title(str(item.get("title") or "")))
    return f"weak:{stripped}{_suffix(item)}" if stripped else None


def _is_spinoff_pair(a: dict, b: dict) -> bool:
    ta = norm_title(str(a.get("title") or ""))
    tb = norm_title(str(b.get("title") or ""))
    if ta == tb:
        return False
    return bool(_SPINOFF_MARKERS.search(ta) or _SPINOFF_MARKERS.search(tb))


def _winner_sort_key(item: dict) -> tuple:
    return (
        SOURCE_PRECEDENCE.get(str(item.get("source") or ""), 99),
        0 if item.get("ends_at") else 1,
        0 if item.get("steam_appid") else 1,
        str(item.get("id") or ""),
    )


def pick_winner(items: list[dict]) -> dict:
    return min(items, key=_winner_sort_key)


def _normalize_splits(splits: Iterable[Iterable[str]] | None) -> set[frozenset[str]]:
    out: set[frozenset[str]] = set()
    for pair in splits or ():
        ids = [str(x).strip() for x in pair if str(x).strip()]
        for i, a in enumerate(ids):
            for b in ids[i + 1 :]:
                if a != b:
                    out.add(frozenset((a, b)))
    return out


class _UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def _group_key(members: list[dict], reasons: set[str]) -> str:
    for prefix in ("appid:", "epic:", "title:", "weak:"):
        hits = sorted(r for r in reasons if r.startswith(prefix))
        if hits:
            return hits[0]
    return "id:" + str(members[0].get("id") or "")


def group_claims(
    items: list[dict],
    *,
    splits: Iterable[Iterable[str]] | None = None,
) -> list[ClaimGroup]:
    """Return dupe groups (size >= 2) over ``items``; singletons are omitted."""
    rows = [it for it in items if isinstance(it, dict) and str(it.get("id") or "").strip()]
    n = len(rows)
    ids = [str(r["id"]).strip() for r in rows]
    split_pairs = _normalize_splits(splits)

    def allowed(i: int, j: int) -> bool:
        return frozenset((ids[i], ids[j])) not in split_pairs

    strong_uf = _UnionFind(n)
    edge_reasons: dict[tuple[int, int], set[str]] = {}
    possible_edges: list[tuple[int, int, str]] = []

    by_key: dict[str, list[int]] = {}
    for idx, row in enumerate(rows):
        for key in strong_keys(row):
            by_key.setdefault(key, []).append(idx)

    for key, members in by_key.items():
        for a_pos, i in enumerate(members):
            for j in members[a_pos + 1 :]:
                if not allowed(i, j):
                    continue
                if key.startswith("appid:") and _is_spinoff_pair(rows[i], rows[j]):
                    possible_edges.append((i, j, key))
                    continue
                strong_uf.union(i, j)
                edge_reasons.setdefault((min(i, j), max(i, j)), set()).add(key)

    weak_by_key: dict[str, list[int]] = {}
    for idx, row in enumerate(rows):
        wk = weak_key(row)
        if wk:
            weak_by_key.setdefault(wk, []).append(idx)
    for key, members in weak_by_key.items():
        for a_pos, i in enumerate(members):
            for j in members[a_pos + 1 :]:
                if allowed(i, j) and strong_uf.find(i) != strong_uf.find(j):
                    possible_edges.append((i, j, key))

    components: dict[int, list[int]] = {}
    for idx in range(n):
        components.setdefault(strong_uf.find(idx), []).append(idx)

    def comp_reasons(member_idx: list[int]) -> set[str]:
        s = set(member_idx)
        out: set[str] = set()
        for (i, j), keys in edge_reasons.items():
            if i in s and j in s:
                out |= keys
        return out

    groups: list[ClaimGroup] = []
    for member_idx in components.values():
        if len(member_idx) < 2:
            continue
        members = [rows[i] for i in member_idx]
        reasons = comp_reasons(member_idx)
        groups.append(
            ClaimGroup(
                key=_group_key(members, reasons),
                winner_id=str(pick_winner(members)["id"]),
                member_ids=[ids[i] for i in member_idx],
                tier="strong",
                reasons=sorted(reasons),
            )
        )

    possible_uf = _UnionFind(n)
    possible_reasons: dict[int, set[str]] = {}
    for i, j, key in possible_edges:
        possible_uf.union(strong_uf.find(i), strong_uf.find(j))
    for i, j, key in possible_edges:
        root = possible_uf.find(strong_uf.find(i))
        possible_reasons.setdefault(root, set()).add(key)
    possible_components: dict[int, list[int]] = {}
    for idx in range(n):
        root = possible_uf.find(strong_uf.find(idx))
        if root in possible_reasons:
            possible_components.setdefault(root, []).append(idx)
    for root, member_idx in possible_components.items():
        strong_roots = {strong_uf.find(i) for i in member_idx}
        if len(strong_roots) < 2:
            continue
        members = [rows[i] for i in member_idx]
        reasons = possible_reasons[root]
        groups.append(
            ClaimGroup(
                key=_group_key(members, reasons),
                winner_id=str(pick_winner(members)["id"]),
                member_ids=[ids[i] for i in member_idx],
                tier="possible",
                reasons=sorted(reasons),
            )
        )

    groups.sort(key=lambda g: (g.tier != "strong", g.key))
    return groups


def merge_group_fields(winner: dict, siblings: Iterable[dict]) -> dict:
    """Fill the winner's missing ``MERGE_FIELDS`` from siblings (precedence order).

    ``ends_at`` takes the earliest sibling deadline so the card never outlives
    the shortest copy of the offer.
    """
    out = dict(winner)
    ordered = sorted((s for s in siblings if s is not winner), key=_winner_sort_key)
    if not out.get("ends_at"):
        ends = sorted(str(s["ends_at"]) for s in ordered if s.get("ends_at"))
        if ends:
            out["ends_at"] = ends[0]
    for key in ("steam_appid", "header_image"):
        if out.get(key) in (None, ""):
            for s in ordered:
                if s.get(key) not in (None, ""):
                    out[key] = s[key]
                    break
    return out


def strong_loser_ids(groups: Iterable[ClaimGroup]) -> set[str]:
    """Ids that lose a strong group (safe to hide/dismiss as dupes)."""
    out: set[str] = set()
    for g in groups:
        if g.tier == "strong":
            out.update(i for i in g.member_ids if i != g.winner_id)
    return out


def groups_by_member(groups: Iterable[ClaimGroup]) -> dict[str, ClaimGroup]:
    """Map member id -> strong group (possible groups excluded)."""
    out: dict[str, ClaimGroup] = {}
    for g in groups:
        if g.tier != "strong":
            continue
        for mid in g.member_ids:
            out[mid] = g
    return out
