"""Tests for fetch_nintendo CLI error handling."""
from __future__ import annotations

import sys
from unittest.mock import patch

from clients.nintendo_client import NintendoCaptureError


def test_capture_error_does_not_mark_invalid(tmp_path, monkeypatch) -> None:
    prof = tmp_path / "profiles" / "nintendo"
    prof.mkdir(parents=True)
    (prof / "Default").mkdir()

    monkeypatch.setattr("fetchers.fetch_nintendo.profile_dir", lambda _p: prof)
    monkeypatch.setattr("fetchers.fetch_nintendo._nintendo_connected", lambda: True)
    monkeypatch.setattr("fetchers.fetch_nintendo.resolve_env", lambda *_a, **_k: "c=1")

    mark_calls: list = []

    def fake_mark_invalid(provider: str, *, error: str = "") -> None:
        mark_calls.append((provider, error))

    monkeypatch.setattr("fetchers.fetch_nintendo.mark_invalid", fake_mark_invalid)

    with patch("fetchers.fetch_nintendo.NintendoClient") as mock_cls:
        mock_cls.return_value.fetch_all_transactions.side_effect = NintendoCaptureError(
            "capture failed"
        )
        import fetchers.fetch_nintendo as fetch_nintendo

        monkeypatch.setattr(sys, "argv", ["fetch_nintendo", "--skip-hltb"])
        code = fetch_nintendo.main()

    assert code == 1
    assert mark_calls == []
