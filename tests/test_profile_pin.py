"""Per-profile PIN gate for local profile switching."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

import server
from shared import profile_paths
from shared.profiles import (
    clear_pin_failures,
    clear_profile_pin,
    create_profile,
    profile_has_pin,
    record_pin_failure,
    set_profile_pin,
    verify_profile_pin,
)


@pytest.fixture()
def pin_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    prof = tmp_path / "profiles"
    monkeypatch.setattr(profile_paths, "ROOT", tmp_path)
    monkeypatch.setattr(profile_paths, "PROFILES_DIR", prof)
    monkeypatch.setattr(profile_paths, "INDEX_FILE", prof / "index.json")
    server._refresh_personal_paths()

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(server.Handler, directory=str(server.ROOT)))
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _post(base: str, path: str, body: dict, *, local: bool = True) -> tuple[int, dict]:
    headers = {"Content-Type": "application/json"}
    if local:
        headers[server._BAKLOG_LOCAL_HEADER] = "1"
    req = urllib.request.Request(
        f"{base}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_set_verify_and_clear_pin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prof = tmp_path / "profiles"
    monkeypatch.setattr(profile_paths, "ROOT", tmp_path)
    monkeypatch.setattr(profile_paths, "PROFILES_DIR", prof)
    monkeypatch.setattr(profile_paths, "INDEX_FILE", prof / "index.json")

    create_profile("Work")
    assert not profile_has_pin("work")
    set_profile_pin("work", "1234")
    assert profile_has_pin("work")
    assert verify_profile_pin("work", "1234")
    assert not verify_profile_pin("work", "9999")
    clear_profile_pin("work", "1234")
    assert not profile_has_pin("work")


def test_switch_requires_pin(pin_server: str) -> None:
    create_profile("Work")
    set_profile_pin("work", "5678")

    status, body = _post(pin_server, "/api/profiles/active", {"id": "work"})
    assert status == 401
    assert body.get("error") == "pin_required"

    status, body = _post(pin_server, "/api/profiles/active", {"id": "work", "pin": "bad"})
    assert status == 401
    assert body.get("error") == "incorrect_pin"

    status, body = _post(pin_server, "/api/profiles/active", {"id": "work", "pin": "5678"})
    assert status == 200
    assert body.get("active") == "work"


def test_pin_rate_limit_after_failures() -> None:
    clear_pin_failures("work")
    for _ in range(5):
        record_pin_failure("work")
    from shared.profiles import _PIN_LOCK_SECONDS, pin_rate_limit_error

    msg = pin_rate_limit_error("work")
    assert msg is not None
    assert str(_PIN_LOCK_SECONDS) in msg
    clear_pin_failures("work")
    assert pin_rate_limit_error("work") is None


def test_set_pin_rate_limited_on_wrong_current(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Brute-forcing the current PIN via set-PIN must lock out, not just the switch route."""
    prof = tmp_path / "profiles"
    monkeypatch.setattr(profile_paths, "ROOT", tmp_path)
    monkeypatch.setattr(profile_paths, "PROFILES_DIR", prof)
    monkeypatch.setattr(profile_paths, "INDEX_FILE", prof / "index.json")

    clear_pin_failures("work")
    create_profile("Work")
    set_profile_pin("work", "1234")
    for _ in range(5):
        with pytest.raises(ValueError, match="current PIN is incorrect"):
            set_profile_pin("work", "5678", current_pin="0000")
    # Locked out now, even with the correct current PIN.
    with pytest.raises(ValueError, match="too many PIN attempts"):
        set_profile_pin("work", "5678", current_pin="1234")
    clear_pin_failures("work")
