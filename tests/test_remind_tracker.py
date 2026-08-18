"""Stop-hook reminder must not ping-pong after the first follow-up."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "scripts" / "hooks" / "remind-tracker.py"


def _load():
    spec = importlib.util.spec_from_file_location("remind_tracker", HOOK)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_first_completed_stop_reminds(tmp_path):
    mod = _load()
    state = tmp_path / "state.json"
    assert mod.should_remind(
        {"status": "completed", "loop_count": 0, "conversation_id": "c1"},
        now=1_000.0,
        path=state,
    )


def test_loop_count_blocks_second_followup(tmp_path):
    mod = _load()
    state = tmp_path / "state.json"
    payload = {"status": "completed", "loop_count": 1, "conversation_id": "c1"}
    assert not mod.should_remind(payload, now=1_000.0, path=state)


def test_same_conversation_is_reminded_once(tmp_path):
    mod = _load()
    state = tmp_path / "state.json"
    first = {"status": "completed", "loop_count": 0, "conversation_id": "chat-9"}
    again = {"status": "completed", "loop_count": 0, "conversation_id": "chat-9"}
    assert mod.should_remind(first, now=1_000.0, path=state)
    assert not mod.should_remind(again, now=1_060.0, path=state)


def test_aborted_stop_is_silent(tmp_path):
    mod = _load()
    state = tmp_path / "state.json"
    assert not mod.should_remind(
        {"status": "aborted", "loop_count": 0, "conversation_id": "c1"},
        now=1_000.0,
        path=state,
    )


def test_missing_conversation_id_is_still_debounced(tmp_path):
    mod = _load()
    state = tmp_path / "state.json"
    payload = {"status": "completed", "loop_count": 0}
    assert mod.should_remind(payload, now=1_000.0, path=state)
    assert not mod.should_remind(payload, now=1_060.0, path=state)


def test_ttl_expiry_allows_a_later_reminder(tmp_path):
    mod = _load()
    state = tmp_path / "state.json"
    payload = {"status": "completed", "loop_count": 0, "conversation_id": "c1"}
    assert mod.should_remind(payload, now=1_000.0, path=state)
    later = 1_000.0 + mod.TTL_SEC + 1
    assert mod.should_remind(payload, now=later, path=state)
