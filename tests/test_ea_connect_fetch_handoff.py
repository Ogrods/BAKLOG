from __future__ import annotations
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from shared import profile_paths

@pytest.fixture
def isolated_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    prof_dir = tmp_path / 'profiles' / 'handoff'
    prof_dir.mkdir(parents=True)
    (prof_dir / 'cache' / 'ea').mkdir(parents=True)
    (tmp_path / 'profiles' / 'index.json').write_text(json.dumps({'active': 'handoff', 'profiles': [{'id': 'handoff', 'label': 'H', 'created_at': 't'}]}), encoding='utf-8')
    monkeypatch.setattr(profile_paths, 'ROOT', tmp_path)
    monkeypatch.setattr(profile_paths, 'PROFILES_DIR', tmp_path / 'profiles')
    monkeypatch.setattr(profile_paths, 'INDEX_FILE', tmp_path / 'profiles' / 'index.json')
    monkeypatch.setenv('BAKLOG_PROFILE', 'handoff')
    return prof_dir

def _owned_game() -> dict:
    return {'originOfferId': 'OFW-HANDOFF-1', 'product': {'name': 'Battlefield 2042', 'gameSlug': 'battlefield-2042', 'baseItem': {'gameType': 'GAME', 'isLauncher': False}, 'gameProductUser': {'ownershipMethods': ['PURCHASE']}}}

def test_resolve_session_skips_browser_when_snapshot_fresh(isolated_profile, monkeypatch) -> None:
    import fetchers.fetch_ea as fetch_ea
    snap = isolated_profile / 'cache' / 'ea' / 'connect_snapshot.json'
    snap.write_text(json.dumps({'captured_at': datetime.now(UTC).isoformat(), 'owned_items': [_owned_game()], 'browser_auth_ok': True}), encoding='utf-8')
    monkeypatch.setattr(fetch_ea, '_load_ea_profile_cookies', lambda: [{'name': 'remid', 'value': 'x'}])
    with patch('fetchers.fetch_ea.launch_ea_profile') as mock_launch:
        token, cookies, dbg = fetch_ea._resolve_session(headless=True)
    mock_launch.assert_not_called()
    assert token == ''
    assert dbg.get('token_source') == 'connect_snapshot'
    assert len(dbg.get('owned_items') or []) == 1

def test_resolve_session_launches_browser_when_snapshot_stale(isolated_profile, monkeypatch) -> None:
    import fetchers.fetch_ea as fetch_ea
    snap = isolated_profile / 'cache' / 'ea' / 'connect_snapshot.json'
    snap.write_text(json.dumps({'captured_at': '2000-01-01T00:00:00+00:00', 'owned_items': [_owned_game()], 'browser_auth_ok': True}), encoding='utf-8')
    ea_prof = isolated_profile / 'cache' / 'auth' / 'profiles' / 'ea' / 'Default'
    ea_prof.mkdir(parents=True)
    monkeypatch.setattr(fetch_ea, 'profile_dir', lambda _p: ea_prof.parent)
    fake_result = type('R', (), {'token': 'cookie', 'cookies': [], 'owned_items': [_owned_game()], 'debug': {'browser_auth_ok': True}})()
    ctx = MagicMock()
    ctx.pages = [MagicMock()]
    with patch('fetchers.fetch_ea.launch_ea_profile') as mock_launch, patch('fetchers.fetch_ea.capture_ea_browser_session', return_value=fake_result):
        mock_launch.return_value.__enter__.return_value = ctx
        monkeypatch.setattr(fetch_ea, 'resolve_env', lambda key, **_k: 'cookie' if key == 'EA_BEARER_TOKEN' else '')
        fetch_ea._resolve_session(headless=True)
    mock_launch.assert_called_once()

def test_fetch_blocks_during_active_auth_with_message(monkeypatch) -> None:
    import fetchers.fetch_ea as fetch_ea
    monkeypatch.setattr(fetch_ea, '_ea_connected', lambda: True)
    monkeypatch.setattr('auth.manager.has_active_sessions', lambda: True)
    with patch('fetchers.fetch_ea._resolve_session') as mock_resolve:
        monkeypatch.setattr(sys, 'argv', ['fetch_ea', '--skip-hltb'])
        code = fetch_ea.main()
        mock_resolve.assert_not_called()
    assert code == 1

def test_main_success_from_connect_snapshot(isolated_profile, monkeypatch) -> None:
    import fetchers.fetch_ea as fetch_ea
    snap = isolated_profile / 'cache' / 'ea' / 'connect_snapshot.json'
    snap.write_text(json.dumps({'captured_at': datetime.now(UTC).isoformat(), 'owned_items': [_owned_game()], 'browser_auth_ok': True}), encoding='utf-8')
    out = isolated_profile / 'games_ea.json'
    monkeypatch.setattr(fetch_ea, '_ea_connected', lambda: True)
    monkeypatch.setattr('auth.manager.has_active_sessions', lambda: False)
    monkeypatch.setattr(fetch_ea, '_load_ea_profile_cookies', lambda: [])
    monkeypatch.setattr(fetch_ea, 'catalog_file', lambda _p: out)

    class Client:

        def get_play_times(self, _slugs):
            return []
    monkeypatch.setattr(fetch_ea, 'EaClient', lambda *_a, **_k: Client())
    with patch('fetchers.fetch_ea.launch_ea_profile') as mock_launch, patch('fetchers.fetch_ea.sniff_ea_bearer') as mock_sniff:
        monkeypatch.setattr(sys, 'argv', ['fetch_ea', '--skip-hltb'])
        code = fetch_ea.main()
        mock_launch.assert_not_called()
        mock_sniff.assert_not_called()
    assert code == 0
    assert out.is_file()
    data = json.loads(out.read_text(encoding='utf-8'))
    assert data['game_count'] == 1