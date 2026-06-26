"""PlayStation Network client via psnawp."""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime

from psnawp_api import PSNAWP
from psnawp_api.core import PSNAWPAuthenticationError, PSNAWPForbiddenError

from fetchers._progress import HeartbeatTimer, heartbeat, progress_line
from shared.library_noise import should_auto_hide_psn_title


class PsnAuthError(Exception):
    """NPSSO token invalid, expired, or profile not accessible."""


def validate_npsso(npsso: str) -> None:
    """Raise PsnAuthError if the NPSSO token is missing or not accepted by PSN."""
    token = (npsso or "").strip()
    if len(token) < 20:
        raise PsnAuthError("NPSSO token is too short.")
    try:
        PsnClient(token).validate_session()
    except PSNAWPAuthenticationError as exc:
        raise PsnAuthError(
            "NPSSO rejected — sign in at playstation.com, open the ssocookie link, and paste a fresh token."
        ) from exc
    except PSNAWPForbiddenError as exc:
        raise PsnAuthError(
            "PSN profile is private. Set trophies/games visibility to Anyone in PSN privacy settings."
        ) from exc


@dataclass
class PsnGameEntry:
    id: str
    np_communication_id: str | None
    title_id: str | None
    concept_id: str | None
    name: str
    image_url: str | None
    platforms: list[str]
    trophy_progress: int | None
    trophies_earned: int | None
    trophies_total: int | None
    has_platinum: bool
    platinum_earned: bool
    playtime_minutes: int
    last_played: str | None
    first_played: str | None
    play_count: int | None
    store_url: str | None


@dataclass
class PsnWishlistEntry:
    id: str
    name: str
    image_url: str | None
    platforms: list[str]
    store_classification: str | None
    localized_classification: str | None
    kind: str
    price: str | None
    price_initial: str | None
    discount_percent: int | None
    store_url: str | None


WISHLIST_GQL_URL = "https://m.np.playstation.com/api/graphql/v1/op"
WISHLIST_OPERATION = "metGetStoreWishlist"
WISHLIST_PERSISTED_HASH = "571149e8aa4d76af7dd33b92e1d6f8f828ebc5fa8f0f6bf51a8324a0e6d71324"


_SUFFIX_NOISE = (
    r"\bps4\s*(?:and|&|\+)?\s*ps5\b",
    r"\bps5\s*(?:and|&|\+)?\s*ps4\b",
    r"\bfor\s+ps5\b",
    r"\bfor\s+ps4\b",
    r"\bps5\b",
    r"\bps4\b",
    r"\bps3\b",
    r"\bps\s*vita\b",
    r"\btrophy\s+set\b",
    r"\btrophies\b",
)
_SUFFIX_RE = re.compile("|".join(_SUFFIX_NOISE))

_ROMAN_WORDS = {
    "i": "1",
    "ii": "2",
    "iii": "3",
    "iv": "4",
    "v": "5",
    "vi": "6",
    "vii": "7",
    "viii": "8",
    "ix": "9",
    "x": "10",
    "xi": "11",
    "xii": "12",
    "xiii": "13",
    "xiv": "14",
    "xv": "15",
}

def _strip_marketing(name: str) -> str:
    return name.replace("\u2122", "").replace("\u00ae", "").replace("\u00a9", "")


def _display_name(name: str) -> str:
    """Fix known broken spacing from PSN trophy/API titles."""
    n = _strip_marketing(name).strip()
    n = re.sub(r"\bT elltale\b", "Telltale", n, flags=re.I)
    return n


def _norm_name(name: str | None) -> str:
    if not name:
        return ""
    n = _strip_marketing(name)
    n = unicodedata.normalize("NFKD", n).lower()
    n = "".join(c for c in n if not unicodedata.combining(c))
    n = re.sub(r"[^a-z0-9\s]", " ", n)
    n = _SUFFIX_RE.sub(" ", n)
    return " ".join(n.split())


def _roman_to_digit(text: str) -> str:
    return " ".join(_ROMAN_WORDS.get(word, word) for word in text.split())


def _dedupe_key(name: str | None) -> str:
    if not name:
        return ""
    base = _strip_marketing(name)
    for sep in (" - ", " – ", " — ", " : "):
        if sep in base:
            base = base.split(sep, 1)[0]
            break
    return _roman_to_digit(_norm_name(base))


def _is_non_game(name: str) -> bool:
    return should_auto_hide_psn_title(name)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _trophy_set_sum(trophy_set) -> int:
    if trophy_set is None:
        return 0
    return sum(
        int(getattr(trophy_set, tier, 0) or 0)
        for tier in ("bronze", "silver", "gold", "platinum")
    )


def _trophy_set_platinum(trophy_set) -> int:
    if trophy_set is None:
        return 0
    return int(getattr(trophy_set, "platinum", 0) or 0)


def _trophy_counts_from_title(trophy) -> tuple[int | None, int | None, bool, bool]:
    """Return (earned, total, has_platinum, platinum_earned) from a TrophyTitle."""
    earned_set = getattr(trophy, "earned_trophies", None)
    defined_set = getattr(trophy, "defined_trophies", None)
    earned = _trophy_set_sum(earned_set)
    total = _trophy_set_sum(defined_set)
    has_platinum = _trophy_set_platinum(defined_set) >= 1
    platinum_earned = _trophy_set_platinum(earned_set) >= 1
    return (
        earned if total else None,
        total if total else None,
        has_platinum,
        platinum_earned,
    )


def _new_stat_agg() -> dict[str, dict]:
    return defaultdict(
        lambda: {"minutes": 0, "play_count": None, "last": None, "first": None}
    )


def _accumulate_stat_into_agg(stat_agg: dict[str, dict], stat: object) -> None:
    """Sum play time across PS4/PS5 (etc.) title_stats rows for the same game name."""
    key = _dedupe_key(getattr(stat, "name", None))
    if not key:
        return
    agg = stat_agg[key]
    play_duration = getattr(stat, "play_duration", None)
    if play_duration:
        agg["minutes"] += int(play_duration.total_seconds() // 60)
    play_count = getattr(stat, "play_count", None)
    if play_count is not None:
        agg["play_count"] = (agg["play_count"] or 0) + play_count
    last = _iso(getattr(stat, "last_played_date_time", None))
    if last and (not agg["last"] or last > agg["last"]):
        agg["last"] = last
    first = _iso(getattr(stat, "first_played_date_time", None))
    if first and (not agg["first"] or first < agg["first"]):
        agg["first"] = first


def _apply_stat_to_entry(
    entry: PsnGameEntry,
    stat: object | None,
    stat_agg: dict[str, dict],
) -> None:
    """Apply per-title stat fields, preferring cross-gen summed play time when present."""
    agg = stat_agg.get(_dedupe_key(entry.name))
    if agg and agg["minutes"]:
        entry.playtime_minutes = agg["minutes"]
    elif stat is not None and getattr(stat, "play_duration", None):
        entry.playtime_minutes = int(stat.play_duration.total_seconds() // 60)
    last = (agg and agg["last"]) or (
        _iso(getattr(stat, "last_played_date_time", None)) if stat is not None else None
    )
    if last:
        entry.last_played = last
    first = (agg and agg["first"]) or (
        _iso(getattr(stat, "first_played_date_time", None)) if stat is not None else None
    )
    if first:
        entry.first_played = first
    count = agg["play_count"] if agg else None
    if count is None and stat is not None:
        count = getattr(stat, "play_count", None)
    if count is not None:
        entry.play_count = count
    if stat is not None and getattr(stat, "title_id", None) and not entry.title_id:
        entry.title_id = stat.title_id
    if stat is not None and getattr(stat, "image_url", None) and not entry.image_url:
        entry.image_url = stat.image_url


def _platform_labels(raw: frozenset) -> list[str]:
    labels: list[str] = []
    for platform in raw:
        label = getattr(platform, "value", str(platform))
        if label in ("PS4", "PS5", "PS3", "PSVITA", "PSP"):
            labels.append(label.replace("PSVITA", "PS Vita"))
    return labels or ["PlayStation"]


_TITLE_ID_PLATFORM_PREFIX = {
    "PPSA": "PS5",
    "CUSA": "PS4",
    "PCSE": "PS Vita",
    "PCSA": "PS Vita",
    "PCSB": "PS Vita",
    "PCSC": "PS Vita",
    "PCSD": "PS Vita",
    "PCSF": "PS Vita",
    "PCSG": "PS Vita",
    "PCSH": "PS Vita",
}


def _platform_from_title_id(title_id: str | None) -> list[str]:
    if not title_id:
        return ["PlayStation"]
    prefix = title_id[:4].upper()
    if prefix in _TITLE_ID_PLATFORM_PREFIX:
        return [_TITLE_ID_PLATFORM_PREFIX[prefix]]
    if prefix.startswith("NP"):
        return ["PS3"]
    return ["PlayStation"]


_PLATFORM_RANK = {"PS5": 5, "PS4": 4, "PS3": 3, "PS Vita": 2, "PSPC": 1, "PlayStation": 0}


def _platform_priority(platforms: list[str]) -> int:
    return max((_PLATFORM_RANK.get(p, 0) for p in platforms), default=0)


def _store_url(concept_id: str | None, np_communication_id: str | None) -> str | None:
    if concept_id:
        return f"https://store.playstation.com/en-us/concept/{concept_id}"
    if np_communication_id:
        return f"https://psnprofiles.com/trophies/{np_communication_id}"
    return None


def _wishlist_store_url(product_id: str) -> str:
    pid = (product_id or "").strip()
    if not pid:
        return "https://store.playstation.com/en-us/"
    if pid.isdigit():
        return f"https://store.playstation.com/en-us/concept/{pid}"
    return f"https://store.playstation.com/en-us/product/{pid}"


def _parse_usd_price(value: str | None) -> float | None:
    if not value:
        return None
    s = value.strip().replace("$", "").replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def _parse_wishlist_price(price_obj: dict | None) -> tuple[str | None, str | None, int | None]:
    if not price_obj:
        return None, None, None
    base = _parse_usd_price(price_obj.get("basePrice"))
    final = _parse_usd_price(price_obj.get("discountedPrice"))
    price_str = price_obj.get("discountedPrice") or price_obj.get("basePrice")
    if price_obj.get("isFree"):
        price_str = "Free"
    price_initial_str = price_obj.get("basePrice")
    discount = None
    if base and final and base > 0 and final < base:
        discount = round(100 * (1 - final / base))
    return price_str, price_initial_str, discount


class PsnClient:
    def __init__(self, npsso: str):
        self.last_dedupe_dropped = 0
        self.last_filtered_non_games = 0
        self.last_title_stats_count = 0
        self.last_trophy_count = 0
        self.last_entitlement_count = 0
        try:
            self._psnawp = PSNAWP(npsso)
            self._client = self._psnawp.me()
        except PSNAWPAuthenticationError as exc:
            raise PsnAuthError(
                "PSN session expired or invalid. Sign in at playstation.com and update PSN_NPSSO in .env."
            ) from exc

    def validate_session(self) -> str:
        try:
            return self._client.online_id
        except PSNAWPForbiddenError as exc:
            raise PsnAuthError(
                "PSN profile is private or inaccessible. Set profile/trophies to Public in PSN privacy settings."
            ) from exc

    def collect_wishlist(self) -> list[PsnWishlistEntry]:
        """Fetch the signed-in user's PlayStation Store wishlist (heart icon).

        Uses the mobile GraphQL gateway ``metGetStoreWishlist`` with the same
        NPSSO session as the library fetcher — no browser cookie required.
        """
        import json

        params = {
            "operationName": WISHLIST_OPERATION,
            "variables": json.dumps({}),
            "extensions": json.dumps(
                {"persistedQuery": {"version": 1, "sha256Hash": WISHLIST_PERSISTED_HASH}}
            ),
        }
        headers = {
            "x-apollo-operation-name": WISHLIST_OPERATION,
            "apollographql-client-name": "PlayStationApp-Web",
            "content-type": "application/json",
        }
        try:
            resp = self._psnawp.authenticator.get(
                url=WISHLIST_GQL_URL,
                params=params,
                headers=headers,
            )
        except PSNAWPAuthenticationError as exc:
            raise PsnAuthError(
                "PSN session expired or invalid. Reconnect PSN on the Connections page."
            ) from exc
        payload = resp.json()
        errors = payload.get("errors") or []
        if errors:
            raise PsnAuthError(f"PSN wishlist GraphQL error: {errors[0].get('message', errors[0])}")
        raw_items = (payload.get("data") or {}).get("storeWishlist") or []
        entries: list[PsnWishlistEntry] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            pid = str(item.get("id") or "").strip()
            if not pid:
                continue
            box = item.get("boxArt") or {}
            image = box.get("url") if isinstance(box, dict) else None
            price, price_initial, discount = _parse_wishlist_price(item.get("price"))
            entries.append(
                PsnWishlistEntry(
                    id=pid,
                    name=_display_name(item.get("name") or f"PSN {pid}"),
                    image_url=image,
                    platforms=[str(p) for p in (item.get("platforms") or []) if p],
                    store_classification=item.get("storeDisplayClassification"),
                    localized_classification=item.get("localizedStoreDisplayClassification"),
                    kind=str(item.get("__typename") or "Product"),
                    price=price,
                    price_initial=price_initial,
                    discount_percent=discount,
                    store_url=_wishlist_store_url(pid),
                )
            )
        return entries

    def probe_library_fingerprint(self) -> tuple[int, str | None]:
        """Cheap title-stats walk: count + newest last_played (for incremental skip)."""
        count = 0
        max_last: str | None = None
        for stat in self._client.title_stats(limit=None):
            count += 1
            last = _iso(getattr(stat, "last_played_date_time", None))
            if last and (max_last is None or last > max_last):
                max_last = last
        return count, max_last

    def _walk_title_stats(self) -> tuple[dict[str, object], dict[str, object], dict, int]:
        stats_by_title_id: dict[str, object] = {}
        stats_by_name: dict[str, object] = {}
        stat_agg = _new_stat_agg()
        count = 0
        for stat in self._client.title_stats(limit=None):
            count += 1
            if stat.title_id:
                stats_by_title_id[stat.title_id] = stat
            if stat.name:
                stats_by_name[_norm_name(stat.name)] = stat
            _accumulate_stat_into_agg(stat_agg, stat)
        return stats_by_title_id, stats_by_name, stat_agg, count

    def _walk_trophy_entries(self) -> tuple[dict[str, PsnGameEntry], int]:
        entries: dict[str, PsnGameEntry] = {}
        count = 0
        for trophy in self._client.trophy_titles(limit=None):
            count += 1
            comm_id = trophy.np_communication_id
            if not comm_id:
                continue
            name = _display_name(trophy.title_name or f"PSN {comm_id}")
            trophies_earned, trophies_total, has_platinum, platinum_earned = (
                _trophy_counts_from_title(trophy)
            )
            entry = PsnGameEntry(
                id=comm_id,
                np_communication_id=comm_id,
                title_id=trophy.np_title_id,
                concept_id=None,
                name=name,
                image_url=trophy.title_icon_url,
                platforms=_platform_labels(trophy.title_platform),
                trophy_progress=trophy.progress,
                trophies_earned=trophies_earned,
                trophies_total=trophies_total,
                has_platinum=has_platinum,
                platinum_earned=platinum_earned,
                playtime_minutes=0,
                last_played=_iso(trophy.last_updated_datetime),
                first_played=None,
                play_count=None,
                store_url=_store_url(None, comm_id),
            )
            entries[comm_id] = entry
        return entries, count

    def _walk_entitlements_raw(self) -> tuple[list, int]:
        raw: list = []
        count = 0
        for entitlement in self._client.game_entitlements(limit=None):
            count += 1
            raw.append(entitlement)
        return raw, count

    def collect_library(self) -> list[PsnGameEntry]:
        hb = HeartbeatTimer(interval=25.0)
        heartbeat("PSN library: loading (parallel API walks)")
        with ThreadPoolExecutor(max_workers=3) as ex:
            f_stats = ex.submit(self._walk_title_stats)
            f_trophy = ex.submit(self._walk_trophy_entries)
            f_ent = ex.submit(self._walk_entitlements_raw)
            stats_by_title_id, stats_by_name, stat_agg, title_stats_count = f_stats.result()
            entries, trophy_count = f_trophy.result()
            entitlements, entitlement_count = f_ent.result()
        self.last_title_stats_count = title_stats_count
        self.last_trophy_count = trophy_count
        self.last_entitlement_count = entitlement_count
        heartbeat(progress_line(0, 0, "PSN title stats", f"{title_stats_count} loaded"))
        heartbeat(progress_line(0, len(entries), "PSN trophies", f"{len(entries)} titles"))

        for entry in entries.values():
            stat = None
            if entry.title_id:
                stat = stats_by_title_id.get(entry.title_id)
            if stat is None:
                stat = stats_by_name.get(_norm_name(entry.name))
            if stat is None:
                continue
            _apply_stat_to_entry(entry, stat, stat_agg)

        seen_title_ids = {e.title_id for e in entries.values() if e.title_id}

        for entitlement in entitlements:
            hb.tick_progress(0, 0, "PSN entitlements")
            if entitlement.get("isGame") is False or entitlement.get("isBeta") is True:
                continue
            title_meta = entitlement.get("titleMeta") or {}
            concept_meta = entitlement.get("conceptMeta") or {}
            game_meta = entitlement.get("gameMeta") or {}
            title_id = title_meta.get("titleId")
            if not title_id or title_id in seen_title_ids:
                continue

            name = _display_name(
                title_meta.get("name")
                or concept_meta.get("name")
                or game_meta.get("name")
                or f"PSN {title_id}"
            )
            concept_id = concept_meta.get("conceptId")
            image = (
                title_meta.get("imageUrl")
                or concept_meta.get("iconUrl")
                or game_meta.get("iconUrl")
            )
            entry_id = title_id
            entries[entry_id] = PsnGameEntry(
                id=entry_id,
                np_communication_id=None,
                title_id=title_id,
                concept_id=concept_id,
                name=name,
                image_url=image,
                platforms=_platform_from_title_id(title_id),
                trophy_progress=None,
                trophies_earned=None,
                trophies_total=None,
                has_platinum=False,
                platinum_earned=False,
                playtime_minutes=0,
                last_played=None,
                first_played=None,
                play_count=None,
                store_url=_store_url(concept_id, None),
            )
            seen_title_ids.add(title_id)

            stat = stats_by_title_id.get(title_id) or stats_by_name.get(_norm_name(name))
            if stat is None:
                continue
            _apply_stat_to_entry(entries[entry_id], stat, stat_agg)

        deduped = self._dedupe_by_name(list(entries.values()))
        self.last_dedupe_dropped = len(entries) - len(deduped)

        games = [e for e in deduped if not _is_non_game(e.name)]
        self.last_filtered_non_games = len(deduped) - len(games)
        return sorted(games, key=lambda g: g.name.lower())

    @staticmethod
    def _dedupe_by_name(entries: list[PsnGameEntry]) -> list[PsnGameEntry]:
        """Collapse cross-platform duplicates by name, preferring PS5 > PS4 > PS3 > Vita."""
        groups: dict[str, list[PsnGameEntry]] = {}
        for entry in entries:
            key = _dedupe_key(entry.name)
            if not key:
                key = entry.id
            groups.setdefault(key, []).append(entry)

        def sort_key(entry: PsnGameEntry) -> tuple:
            return (
                _platform_priority(entry.platforms),
                1 if entry.trophy_progress is not None else 0,
                1 if entry.playtime_minutes else 0,
                1 if entry.title_id else 0,
            )

        result: list[PsnGameEntry] = []
        for group in groups.values():
            if len(group) == 1:
                result.append(group[0])
                continue
            group.sort(key=sort_key, reverse=True)
            keeper = group[0]
            for sibling in group[1:]:
                if sibling.playtime_minutes > keeper.playtime_minutes:
                    keeper.playtime_minutes = sibling.playtime_minutes
                if sibling.last_played and (
                    not keeper.last_played or sibling.last_played > keeper.last_played
                ):
                    keeper.last_played = sibling.last_played
                if sibling.first_played and (
                    not keeper.first_played or sibling.first_played < keeper.first_played
                ):
                    keeper.first_played = sibling.first_played
                if keeper.trophy_progress is None and sibling.trophy_progress is not None:
                    keeper.trophy_progress = sibling.trophy_progress
                if keeper.play_count is None and sibling.play_count is not None:
                    keeper.play_count = sibling.play_count
                if not keeper.image_url and sibling.image_url:
                    keeper.image_url = sibling.image_url
                if not keeper.np_communication_id and sibling.np_communication_id:
                    keeper.np_communication_id = sibling.np_communication_id
                if not keeper.title_id and sibling.title_id:
                    keeper.title_id = sibling.title_id
                if not keeper.concept_id and sibling.concept_id:
                    keeper.concept_id = sibling.concept_id
                if not keeper.store_url and sibling.store_url:
                    keeper.store_url = sibling.store_url
            # Rebuild store_url so it tracks the merged concept_id. Without
            # this, a trophy-only keeper that inherits concept_id from a
            # sibling keeps the psnprofiles URL it was built with — the link
            # in the dashboard then goes to PSNProfiles instead of the PSN
            # store page for that concept.
            rebuilt = _store_url(keeper.concept_id, keeper.np_communication_id)
            if rebuilt:
                keeper.store_url = rebuilt
            result.append(keeper)
        return result
