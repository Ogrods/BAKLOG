from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from clients.psn_client import PsnClient, _accumulate_stat_into_agg, _apply_stat_to_entry, _new_stat_agg


def _stat(*, title_id, name, hours=0, minutes=0, play_count=None, last=None, first=None):
    return SimpleNamespace(
        title_id=title_id,
        name=name,
        play_duration=timedelta(hours=hours, minutes=minutes) if hours or minutes else None,
        play_count=play_count,
        last_played_date_time=last,
        first_played_date_time=first,
        image_url=None,
    )


def _trophy_set(*, bronze=0, silver=0, gold=0, platinum=0):
    return SimpleNamespace(bronze=bronze, silver=silver, gold=gold, platinum=platinum)


def _trophy(
    *, comm_id="NPWR22022_00", name="Fortnite", title_id="PPSA01922_00", platform="PS5", earned=None, defined=None
):
    return SimpleNamespace(
        np_communication_id=comm_id,
        title_name=name,
        np_title_id=title_id,
        title_platform=[SimpleNamespace(value=platform)],
        title_icon_url=None,
        progress=10,
        last_updated_datetime=datetime(2024, 2, 17, 20, 21, 43),
        earned_trophies=earned,
        defined_trophies=defined,
    )


class _FakePsnMe:
    def __init__(self, stats, trophies, entitlements=None):
        self._stats = stats
        self._trophies = trophies
        self._entitlements = entitlements or []

    def title_stats(self, limit=None):
        yield from self._stats

    def trophy_titles(self, limit=None):
        yield from self._trophies

    def game_entitlements(self, limit=None):
        yield from self._entitlements


def test_parallel_collect_walks_run_concurrently():
    import threading
    import time

    lock = threading.Lock()
    active = set()
    peak = 0

    def track(name):
        with lock:
            active.add(name)
            nonlocal peak
            peak = max(peak, len(active))
        time.sleep(0.05)
        with lock:
            active.discard(name)

    class _SlowMe:
        def title_stats(self, limit=None):
            track("stats")
            yield from [_stat(title_id="T1", name="Game A")]

        def trophy_titles(self, limit=None):
            track("trophy")
            yield from [_trophy()]

        def game_entitlements(self, limit=None):
            track("ent")
            yield from []

    client = object.__new__(PsnClient)
    client._client = _SlowMe()
    client.last_dedupe_dropped = 0
    client.last_filtered_non_games = 0
    games = client.collect_library()
    assert peak >= 2
    assert len(games) >= 1


def test_cross_gen_playtime_summed():
    ps4_min = int(timedelta(hours=2304, minutes=16).total_seconds() // 60)
    ps5_min = int(timedelta(hours=168).total_seconds() // 60)
    stats = [
        _stat(title_id="CUSA07022_00", name="Fortnite", hours=2304, minutes=16),
        _stat(title_id="PPSA01922_00", name="Fortnite", hours=168),
    ]
    client = object.__new__(PsnClient)
    client._client = _FakePsnMe(stats, [_trophy(title_id="PPSA01922_00")])
    games = client.collect_library()
    fn = next((g for g in games if g.name == "Fortnite"))
    assert fn.playtime_minutes == ps4_min + ps5_min


def test_cross_gen_last_first_play_count_merged():
    stats = [
        _stat(
            title_id="CUSA07022_00",
            name="Fortnite",
            hours=100,
            play_count=50,
            last=datetime(2024, 6, 1, tzinfo=UTC),
            first=datetime(2018, 1, 1, tzinfo=UTC),
        ),
        _stat(
            title_id="PPSA01922_00",
            name="Fortnite",
            hours=10,
            play_count=5,
            last=datetime(2025, 1, 1, tzinfo=UTC),
            first=datetime(2020, 1, 1, tzinfo=UTC),
        ),
    ]
    client = object.__new__(PsnClient)
    client._client = _FakePsnMe(stats, [_trophy()])
    fn = next((g for g in client.collect_library() if g.name == "Fortnite"))
    assert fn.play_count == 55
    assert fn.last_played.startswith("2025-01-01")
    assert fn.first_played.startswith("2018-01-01")


def test_single_platform_not_inflated():
    stats = [_stat(title_id="CUSA12345_00", name="Solo Game", hours=42)]
    client = object.__new__(PsnClient)
    client._client = _FakePsnMe(stats, [_trophy(comm_id="NPWR1", name="Solo Game", title_id="CUSA12345_00")])
    solo = next((g for g in client.collect_library() if g.name == "Solo Game"))
    assert solo.playtime_minutes == 42 * 60


def test_edition_suffix_groups_via_dedupe_key():
    stat_agg = _new_stat_agg()
    _accumulate_stat_into_agg(stat_agg, _stat(title_id="A", name="Game Name - Deluxe Edition", hours=10))
    _accumulate_stat_into_agg(stat_agg, _stat(title_id="B", name="Game Name", hours=5))
    from clients.psn_client import PsnGameEntry

    entry = PsnGameEntry(
        id="x",
        np_communication_id="x",
        title_id="A",
        concept_id=None,
        name="Game Name",
        image_url=None,
        platforms=["PS5"],
        trophy_progress=None,
        trophies_earned=None,
        trophies_total=None,
        has_platinum=False,
        platinum_earned=False,
        playtime_minutes=0,
        last_played=None,
        first_played=None,
        play_count=None,
        store_url=None,
    )
    _apply_stat_to_entry(entry, _stat(title_id="A", name="Game Name", hours=5), stat_agg)
    assert entry.playtime_minutes == 15 * 60


def test_trophy_counts_and_platinum_flags():
    earned = _trophy_set(bronze=10, silver=4, gold=2, platinum=1)
    defined = _trophy_set(bronze=20, silver=8, gold=4, platinum=1)
    client = object.__new__(PsnClient)
    client._client = _FakePsnMe(
        [], [_trophy(comm_id="NPWR99999_00", name="Platinum Game", earned=earned, defined=defined)]
    )
    game = next((g for g in client.collect_library() if g.name == "Platinum Game"))
    assert game.trophies_earned == 17
    assert game.trophies_total == 33
    assert game.has_platinum is True
    assert game.platinum_earned is True


def test_entitlement_beta_and_non_game_skipped():
    client = object.__new__(PsnClient)
    client._client = _FakePsnMe(
        [],
        [],
        entitlements=[
            {"isGame": False, "titleMeta": {"titleId": "CUSA00001_00", "name": "Not A Game"}},
            {"isBeta": True, "titleMeta": {"titleId": "CUSA00002_00", "name": "Beta Build"}},
            {
                "titleMeta": {
                    "titleId": "CUSA00003_00",
                    "name": "Real Game",
                    "imageUrl": "https://example.com/title.jpg",
                },
                "conceptMeta": {"conceptId": "123", "name": "Real Game"},
                "gameMeta": {"name": "Real Game", "iconUrl": "https://example.com/icon.jpg"},
            },
        ],
    )
    games = client.collect_library()
    names = {g.name for g in games}
    assert "Not A Game" not in names
    assert "Beta Build" not in names
    assert "Real Game" in names
