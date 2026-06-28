import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "fetchers" / "manifest.json").read_text(encoding="utf-8"))
_STALL_GUARD_EXEMPT = frozenset({"claims"})
FETCHER_ENTRIES = [
    e
    for e in MANIFEST["fetchers"]
    if e.get("key") not in _STALL_GUARD_EXEMPT and e["script"].startswith("fetchers/fetch_")
]


@pytest.mark.parametrize("entry", FETCHER_ENTRIES, ids=[e["key"] for e in FETCHER_ENTRIES])
def test_fetcher_configures_line_buffered_stdout(entry):
    text = (ROOT / entry["script"]).read_text(encoding="utf-8")
    assert "configure_stdout()" in text, f"{entry['script']} must call configure_stdout() in main"


@pytest.mark.parametrize("entry", FETCHER_ENTRIES, ids=[e["key"] for e in FETCHER_ENTRIES])
def test_fetcher_emits_stall_heartbeats(entry):
    text = (ROOT / entry["script"]).read_text(encoding="utf-8")
    has_timer = "HeartbeatTimer" in text
    has_pulse = "run_with_heartbeat" in text
    assert has_timer or has_pulse, (
        f"{entry['script']} must use HeartbeatTimer and/or run_with_heartbeat so long network loops keep stdout alive under the 180s stall watchdog"
    )


@pytest.mark.parametrize("entry", FETCHER_ENTRIES, ids=[e["key"] for e in FETCHER_ENTRIES])
def test_fetcher_progress_prints_flush(entry):
    text = (ROOT / entry["script"]).read_text(encoding="utf-8")
    if 'print(f"[' not in text and "print(f'[" not in text:
        pytest.skip(f"{entry['script']} has no [i/N] progress lines")
    assert "flush=True" in text, (
        f"{entry['script']} must pass flush=True on progress prints (or every numbered progress print) for pipe capture"
    )
