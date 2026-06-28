from __future__ import annotations
from shared.update_snooze import is_version_dismissed, read_dismissed_version, write_dismissed_version

def test_dismiss_round_trip(tmp_path) -> None:
    root = tmp_path / 'data'
    assert read_dismissed_version(root) is None
    write_dismissed_version(root, '0.8.26')
    assert read_dismissed_version(root) == '0.8.26'
    assert is_version_dismissed(root, '0.8.26') is True
    assert is_version_dismissed(root, '0.8.27') is False