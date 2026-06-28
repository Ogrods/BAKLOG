"""SSE stream resume cursor (?since=, Last-Event-ID) and replay filtering."""
from __future__ import annotations

from pathlib import Path

import pytest

import server


class _FakeHandler:
    def __init__(self, path: str, headers: dict[str, str] | None = None) -> None:
        self.path = path
        _hdrs = headers or {}

        class _Hdrs:
            def get(self, key: str, default: str | None = None) -> str | None:
                return _hdrs.get(key, default)

        self.headers = _Hdrs()


@pytest.fixture()
def runs_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    runs_dir = tmp_path / "runs"
    def _runs_dir_fn(*, profile_id=None):
        return runs_dir

    monkeypatch.setattr("shared.profile_paths.runs_dir", _runs_dir_fn)
    monkeypatch.setattr(server, "runs_dir", _runs_dir_fn)
    monkeypatch.setattr(server, "RUNS_DIR", runs_dir)
    monkeypatch.setitem(
        server.FETCHERS,
        "demo",
        {
            "label": "Demo",
            "argv": [server.sys.executable, "-c", "print('ok')"],
            "refreshArgs": [],
            "metaKey": "demo",
            "group": "library",
            "color": "#fff",
            "requires": [],
        },
    )
    return runs_dir


def test_replay_lines_filters_since(runs_env):
    runs_dir = runs_env
    run = server.Run("demo", runs_dir=runs_dir)
    for i in range(5):
        run.add_line("stdout", f"line{i}")
    replay = run.replay_lines(since=3)
    texts = [m["text"] for m in replay]
    assert texts == ["line3", "line4"]
    assert all(m.get("seq", 0) > 3 for m in replay)


def test_line_count_reflects_total_not_ring_buffer(runs_env):
    runs_dir = runs_env
    run = server.Run("demo", runs_dir=runs_dir)
    for i in range(3):
        run.add_line("stdout", f"x{i}")
    summary = run.to_summary()
    assert summary["line_count"] == 3


def test_attach_listener_replay_respects_since(runs_env):
    runs_dir = runs_env
    run = server.Run("demo", runs_dir=runs_dir)
    for i in range(5):
        run.add_line("stdout", f"l{i}")
    _q, replay, _done = run.attach_listener(since=3)
    texts = [m["text"] for m in replay]
    assert texts == ["l3", "l4"]
    assert all(int(m["seq"]) > 3 for m in replay)


def test_stream_resume_since_query_and_header():
    h = _FakeHandler("/api/stream/abc?since=5", {"Last-Event-ID": "3"})
    assert server._stream_resume_since(h) == 5
    h2 = _FakeHandler("/api/stream/abc", {"Last-Event-ID": "7"})
    assert server._stream_resume_since(h2) == 7


def test_sse_format_includes_event_id():
    chunk = server._sse_format("line", {"seq": 9, "text": "hi"}, event_id=9)
    text = chunk.decode("utf-8")
    assert "id: 9\n" in text
    assert "event: line\n" in text
    assert '"hi"' in text
