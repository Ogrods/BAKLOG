import time
from unittest.mock import patch

import pytest

import scheduler as sched

FETCHERS = {
    "steam": {"group": "library", "metaKey": "steam", "requires": [], "platforms": [], "refreshArgs": ["--refresh"]},
    "gog": {"group": "library", "metaKey": "gog", "requires": [], "platforms": [], "refreshArgs": []},
    "hltb": {"group": "enrich", "metaKey": "hltb", "requires": [], "platforms": []},
    "itad": {"group": "prices", "metaKey": "itad", "requires": [], "platforms": []},
}


class FakeManager:
    def __init__(self, *, active=None, queue=None, history=None):
        self._snap = {"active": active, "queue": queue or [], "history": history or []}
        self.submitted = []

    def snapshot(self):
        return self._snap

    def submit(self, key, refresh=False):
        self.submitted.append((key, refresh))
        return type("R", (), {"id": "r1", "key": key})()


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(sched, "get_active_profile_id", lambda: "testprof")
    monkeypatch.setattr(sched, "runs_dir", lambda *, profile_id=None: tmp_path / "runs")
    monkeypatch.setattr(sched, "personal_dir", lambda *, profile_id=None: tmp_path / "data")


def _make(manager, *, is_pro=True, missing=lambda reqs: list(reqs)):
    return sched.BackgroundScheduler(
        manager=manager, fetchers=FETCHERS, missing_requirements=missing, is_pro_fn=lambda: is_pro
    )


def _set_ages(monkeypatch, ages, default=0.0):
    monkeypatch.setattr(sched, "_catalog_age_sec", lambda mk, pid, now: ages.get(mk, default))


def test_skips_when_not_pro(monkeypatch):
    _set_ages(monkeypatch, {"steam": sched.DEFAULT_STALE_AGE_SEC + 1})
    mgr = FakeManager()
    assert _make(mgr, is_pro=False).tick(now=time.time()) is None
    assert mgr.submitted == []


def test_enqueues_stalest_store_with_refresh(monkeypatch):
    _set_ages(monkeypatch, {"steam": sched.DEFAULT_STALE_AGE_SEC + 100, "gog": 10})
    mgr = FakeManager()
    key = _make(mgr).tick(now=time.time())
    assert key == "steam"
    assert mgr.submitted == [("steam", True)]


def test_picks_stalest_and_uses_full_fetch_without_refreshargs(monkeypatch):
    _set_ages(monkeypatch, {"steam": sched.DEFAULT_STALE_AGE_SEC + 10, "gog": sched.DEFAULT_STALE_AGE_SEC + 9999})
    mgr = FakeManager()
    key = _make(mgr).tick(now=time.time())
    assert key == "gog"
    assert mgr.submitted == [("gog", False)]


def test_never_fetched_counts_as_stale(monkeypatch):
    _set_ages(monkeypatch, {"steam": None, "gog": 10})
    mgr = FakeManager()
    assert _make(mgr).tick(now=time.time()) == "steam"


def test_skips_when_in_flight(monkeypatch):
    _set_ages(monkeypatch, {"steam": sched.DEFAULT_STALE_AGE_SEC + 100})
    mgr = FakeManager(active={"key": "gog", "status": "running"})
    assert _make(mgr).tick(now=time.time()) is None
    assert mgr.submitted == []


def test_skips_when_queue_nonempty(monkeypatch):
    _set_ages(monkeypatch, {"steam": sched.DEFAULT_STALE_AGE_SEC + 100})
    mgr = FakeManager(queue=[{"key": "gog"}])
    assert _make(mgr).tick(now=time.time()) is None


def test_respects_stagger_window(monkeypatch):
    _set_ages(monkeypatch, {"steam": sched.DEFAULT_STALE_AGE_SEC + 100})
    mgr = FakeManager()
    s = _make(mgr)
    now = time.time()
    assert s.tick(now=now) == "steam"
    assert s.tick(now=now + 60) is None
    assert mgr.submitted == [("steam", True)]


def test_skips_fetchers_with_missing_credentials(monkeypatch):
    _set_ages(monkeypatch, {"steam": sched.DEFAULT_STALE_AGE_SEC + 100})
    fetchers = {
        "steam": {
            "group": "library",
            "metaKey": "steam",
            "requires": [{"env": "STEAM_API_KEY"}],
            "platforms": [],
            "refreshArgs": ["--refresh"],
        }
    }
    mgr = FakeManager()
    s = sched.BackgroundScheduler(
        manager=mgr,
        fetchers=fetchers,
        missing_requirements=lambda reqs: ["STEAM_API_KEY"] if reqs else [],
        is_pro_fn=lambda: True,
    )
    assert s.tick(now=time.time()) is None
    assert mgr.submitted == []


def test_skips_fetcher_on_auth_cooldown(monkeypatch):
    _set_ages(monkeypatch, {"steam": sched.DEFAULT_STALE_AGE_SEC + 100})
    now = time.time()
    history = [{"key": "steam", "failure_kind": "auth", "ended_at": now - 60}]
    mgr = FakeManager(history=history)
    assert _make(mgr).tick(now=now) is None
    assert mgr.submitted == []


def test_skips_auto_fetch_disabled_launcher(monkeypatch):
    monkeypatch.setattr(
        sched,
        "_catalog_age_sec",
        lambda mk, pid, now: {"amazon": sched.DEFAULT_STALE_AGE_SEC + 9999, "steam": 10}.get(mk, 10),
    )
    fetchers = {
        "steam": {"group": "library", "metaKey": "steam", "requires": [], "platforms": []},
        "amazon": {"group": "library", "metaKey": "amazon", "requires": [], "platforms": [], "autoFetch": False},
    }
    mgr = FakeManager()
    s = sched.BackgroundScheduler(
        manager=mgr, fetchers=fetchers, missing_requirements=lambda reqs: list(reqs), is_pro_fn=lambda: True
    )
    assert s.tick(now=time.time()) is None
    assert mgr.submitted == []


def test_enrichers_and_prices_never_eligible(monkeypatch):
    _set_ages(monkeypatch, {"hltb": sched.DEFAULT_STALE_AGE_SEC + 100, "itad": sched.DEFAULT_STALE_AGE_SEC + 100})
    mgr = FakeManager()
    assert _make(mgr).tick(now=time.time()) is None


def test_probe_runs_when_due_and_pro(monkeypatch):
    _set_ages(monkeypatch, {"steam": 10})
    mgr = FakeManager()
    s = _make(mgr)
    now = time.time()
    with patch("auth.connection_probe.probe_due", return_value=True) as due:
        with patch("auth.connection_probe.run_connection_probe") as probe:
            assert s.tick(now=now) is None
    due.assert_called_once()
    probe.assert_called_once()
    assert mgr.submitted == []


def test_probe_skipped_when_not_due(monkeypatch):
    _set_ages(monkeypatch, {"steam": sched.DEFAULT_STALE_AGE_SEC + 100})
    mgr = FakeManager()
    with patch("auth.connection_probe.probe_due", return_value=False):
        with patch("auth.connection_probe.run_connection_probe") as probe:
            _make(mgr).tick(now=time.time())
    probe.assert_not_called()


def test_probe_skipped_when_not_pro(monkeypatch):
    mgr = FakeManager()
    with patch("auth.connection_probe.run_connection_probe") as probe:
        _make(mgr, is_pro=False).tick(now=time.time())
    probe.assert_not_called()


def test_probe_skipped_when_scheduler_disabled(monkeypatch):
    mgr = FakeManager()
    s = _make(mgr)
    monkeypatch.setattr(
        s,
        "_load_config",
        lambda _pid: {
            "enabled": False,
            "stale_age_sec": sched.DEFAULT_STALE_AGE_SEC,
            "stagger_sec": sched.DEFAULT_STAGGER_SEC,
            "probe_interval_sec": sched.DEFAULT_PROBE_INTERVAL_SEC,
            "quiet_start_hour": None,
            "quiet_end_hour": None,
        },
    )
    with patch("auth.connection_probe.run_connection_probe") as probe:
        s.tick(now=time.time())
    probe.assert_not_called()
