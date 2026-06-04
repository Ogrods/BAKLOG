"""Tests for PSN library playtime aggregation (PS4 + PS5 cross-gen sum)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from psn_client import PsnClient, _accumulate_stat_into_agg, _apply_stat_to_entry, _new_stat_agg


def _stat(
    *,
    title_id: str,
    name: str,
    hours: int = 0,
    minutes: int = 0,
    play_count: int | None = None,
    last: datetime | None = None,
    first: datetime | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        title_id=title_id,
        name=name,
        play_duration=timedelta(hours=hours, minutes=minutes) if hours or minutes else None,
        play_count=play_count,
        last_played_date_time=last,
        first_played_date_time=first,
        image_url=None,
    )


def _trophy(
    *,
    comm_id: str = "NPWR22022_00",
    name: str = "Fortnite",
    title_id: str = "PPSA01922_00",
    platform: str = "PS5",
) -> SimpleNamespace:
    return SimpleNamespace(
        np_communication_id=comm_id,
        title_name=name,
        np_title_id=title_id,
        title_platform=[SimpleNamespace(value=platform)],
        title_icon_url=None,
        progress=10,
        last_updated_datetime=datetime(2024, 2, 17, 20, 21, 43),
    )


class _FakePsnMe:
    def __init__(
        self,
        stats: list,
        trophies: list,
        entitlements: list | None = None,
    ) -> None:
        self._stats = stats
        self._trophies = trophies
        self._entitlements = entitlements or []

    def title_stats(self, limit=None):
        yield from self._stats

    def trophy_titles(self, limit=None):
        yield from self._trophies

    def game_entitlements(self, limit=None):
        yield from self._entitlements


def test_cross_gen_playtime_summed() -> None:
    ps4_min = int(timedelta(hours=2304, minutes=16).total_seconds() // 60)
    ps5_min = int(timedelta(hours=168).total_seconds() // 60)
    stats = [
        _stat(title_id="CUSA07022_00", name="Fortnite", hours=2304, minutes=16),
        _stat(title_id="PPSA01922_00", name="Fortnite", hours=168),
    ]
    client = object.__new__(PsnClient)
    client._client = _FakePsnMe(stats, [_trophy(title_id="PPSA01922_00")])
    games = client.collect_library()
    fn = next(g for g in games if g.name == "Fortnite")
    assert fn.playtime_minutes == ps4_min + ps5_min


def test_cross_gen_last_first_play_count_merged() -> None:
    stats = [
        _stat(
            title_id="CUSA07022_00",
            name="Fortnite",
            hours=100,
            play_count=50,
            last=datetime(2024, 6, 1, tzinfo=timezone.utc),
            first=datetime(2018, 1, 1, tzinfo=timezone.utc),
        ),
        _stat(
            title_id="PPSA01922_00",
            name="Fortnite",
            hours=10,
            play_count=5,
            last=datetime(2025, 1, 1, tzinfo=timezone.utc),
            first=datetime(2020, 1, 1, tzinfo=timezone.utc),
        ),
    ]
    client = object.__new__(PsnClient)
    client._client = _FakePsnMe(stats, [_trophy()])
    fn = next(g for g in client.collect_library() if g.name == "Fortnite")
    assert fn.play_count == 55
    assert fn.last_played.startswith("2025-01-01")
    assert fn.first_played.startswith("2018-01-01")


def test_single_platform_not_inflated() -> None:
    stats = [_stat(title_id="CUSA12345_00", name="Solo Game", hours=42)]
    client = object.__new__(PsnClient)
    client._client = _FakePsnMe(
        stats,
        [_trophy(comm_id="NPWR1", name="Solo Game", title_id="CUSA12345_00")],
    )
    solo = next(g for g in client.collect_library() if g.name == "Solo Game")
    assert solo.playtime_minutes == 42 * 60


def test_edition_suffix_groups_via_dedupe_key() -> None:
    stat_agg = _new_stat_agg()
    _accumulate_stat_into_agg(
        stat_agg,
        _stat(title_id="A", name="Game Name - Deluxe Edition", hours=10),
    )
    _accumulate_stat_into_agg(
        stat_agg,
        _stat(title_id="B", name="Game Name", hours=5),
    )
    from psn_client import PsnGameEntry

    entry = PsnGameEntry(
        id="x",
        np_communication_id="x",
        title_id="A",
        concept_id=None,
        name="Game Name",
        image_url=None,
        platforms=["PS5"],
        trophy_progress=None,
        playtime_minutes=0,
        last_played=None,
        first_played=None,
        play_count=None,
        store_url=None,
    )
    _apply_stat_to_entry(entry, _stat(title_id="A", name="Game Name", hours=5), stat_agg)
    assert entry.playtime_minutes == 15 * 60
