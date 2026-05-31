"""PlayStation Network client via psnawp."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime

from psnawp_api import PSNAWP
from psnawp_api.core import PSNAWPAuthenticationError, PSNAWPForbiddenError


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
    playtime_minutes: int
    last_played: str | None
    first_played: str | None
    play_count: int | None
    store_url: str | None


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

_NON_GAME_EXACT = frozenset(
    {
        "amazon prime video",
        "disney plus",
        "disney",
        "spotify",
        "youtube",
        "twitch",
        "netflix",
        "hulu",
        "watchesn",
        "watchespn",
        "pluto tv",
        "sharefactory",
        "share factory studio",
        "the playroom",
        "project catch",
        "directv nfl sunday ticket",
    }
)

_NON_GAME_PATTERNS = (
    re.compile(r"\bdemo\b"),
    re.compile(r"\bopen beta\b"),
    re.compile(r"\bbeta\b"),
    re.compile(r"\bb e t a\b"),
    re.compile(r"\btrial version\b"),
    re.compile(r"\bsoundtrack\b"),
    re.compile(r"\bart book\b"),
    re.compile(r"\bdigital deluxe soundtrack\b"),
    re.compile(r"^dlc\b"),
    re.compile(r"\btrophy set$"),
    re.compile(r"\btrophies$"),
    re.compile(r"\btheme$"),
    re.compile(r"\bdynamic theme$"),
    re.compile(r"\bwallpaper$"),
    re.compile(r"\bavatar pack\b"),
    re.compile(r"^cusa\d+_\d+$"),
    re.compile(r"^ppsa\d+_\d+$"),
    re.compile(r"^up\d+-cusa\d+_\d+$"),
    re.compile(r"^npwr\d+_\d+$"),
)


def _strip_marketing(name: str) -> str:
    return name.replace("\u2122", "").replace("\u00ae", "").replace("\u00a9", "")


def _display_name(name: str) -> str:
    """Fix known broken spacing from PSN trophy/API titles."""
    n = _strip_marketing(name).strip()
    n = re.sub(r"\bT elltale\b", "Telltale", n, flags=re.I)
    return n


def _norm_name_raw(name: str | None) -> str:
    """Normalize for filtering — does not strip trophy/platform suffixes."""
    if not name:
        return ""
    n = _strip_marketing(name)
    n = unicodedata.normalize("NFKD", n).lower()
    n = "".join(c for c in n if not unicodedata.combining(c))
    n = re.sub(r"[^a-z0-9\s]", " ", n)
    return " ".join(n.split())


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
    raw = name.strip()
    if re.fullmatch(r"(?i)(?:UP\d+-)?(CUSA|PPSA|NPWR)\d+_\d+$", raw):
        return True
    norm = _norm_name_raw(name)
    if not norm:
        return True
    if norm in _NON_GAME_EXACT:
        return True
    return any(p.search(norm) for p in _NON_GAME_PATTERNS)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


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


class PsnClient:
    def __init__(self, npsso: str):
        self.last_dedupe_dropped = 0
        self.last_filtered_non_games = 0
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

    def collect_library(self) -> list[PsnGameEntry]:
        stats_by_title_id: dict[str, object] = {}
        stats_by_name: dict[str, object] = {}
        for stat in self._client.title_stats(limit=None):
            if stat.title_id:
                stats_by_title_id[stat.title_id] = stat
            if stat.name:
                stats_by_name[_norm_name(stat.name)] = stat

        entries: dict[str, PsnGameEntry] = {}

        for trophy in self._client.trophy_titles(limit=None):
            comm_id = trophy.np_communication_id
            if not comm_id:
                continue
            name = _display_name(trophy.title_name or f"PSN {comm_id}")
            entry = PsnGameEntry(
                id=comm_id,
                np_communication_id=comm_id,
                title_id=trophy.np_title_id,
                concept_id=None,
                name=name,
                image_url=trophy.title_icon_url,
                platforms=_platform_labels(trophy.title_platform),
                trophy_progress=trophy.progress,
                playtime_minutes=0,
                last_played=_iso(trophy.last_updated_datetime),
                first_played=None,
                play_count=None,
                store_url=_store_url(None, comm_id),
            )
            entries[comm_id] = entry

        for entry in entries.values():
            stat = None
            if entry.title_id:
                stat = stats_by_title_id.get(entry.title_id)
            if stat is None:
                stat = stats_by_name.get(_norm_name(entry.name))
            if stat is None:
                continue
            if stat.play_duration:
                entry.playtime_minutes = int(stat.play_duration.total_seconds() // 60)
            if stat.last_played_date_time:
                entry.last_played = _iso(stat.last_played_date_time)
            if stat.first_played_date_time:
                entry.first_played = _iso(stat.first_played_date_time)
            if stat.play_count is not None:
                entry.play_count = stat.play_count
            if stat.title_id and not entry.title_id:
                entry.title_id = stat.title_id
            if stat.image_url and not entry.image_url:
                entry.image_url = stat.image_url

        seen_title_ids = {e.title_id for e in entries.values() if e.title_id}

        for entitlement in self._client.game_entitlements(limit=None):
            title_meta = entitlement.get("titleMeta") or {}
            concept_meta = entitlement.get("conceptMeta") or {}
            title_id = title_meta.get("titleId")
            if not title_id or title_id in seen_title_ids:
                continue

            name = _display_name(
                title_meta.get("name")
                or concept_meta.get("name")
                or (entitlement.get("gameMeta") or {}).get("name")
                or f"PSN {title_id}"
            )
            concept_id = concept_meta.get("conceptId")
            image = title_meta.get("imageUrl") or concept_meta.get("iconUrl")
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
            if stat.play_duration:
                entries[entry_id].playtime_minutes = int(stat.play_duration.total_seconds() // 60)
            if stat.last_played_date_time:
                entries[entry_id].last_played = _iso(stat.last_played_date_time)
            if stat.first_played_date_time:
                entries[entry_id].first_played = _iso(stat.first_played_date_time)
            if stat.play_count is not None:
                entries[entry_id].play_count = stat.play_count
            if stat.image_url and not entries[entry_id].image_url:
                entries[entry_id].image_url = stat.image_url

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
            result.append(keeper)
        return result
