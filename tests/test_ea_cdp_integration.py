from __future__ import annotations
import os
import subprocess
import sys
from pathlib import Path
import pytest
ROOT = Path(__file__).resolve().parents[1]

@pytest.mark.integration
def test_ea_diag_session_on_active_profile() -> None:
    if os.getenv('BAKLOG_SKIP_CDP_INTEGRATION'):
        pytest.skip('BAKLOG_SKIP_CDP_INTEGRATION set')
    from auth.manager import get_provider_blob
    from auth.secrets import profile_dir
    if get_provider_blob('ea').get('status') != 'connected':
        pytest.skip('EA not connected on active profile')
    prof = profile_dir('ea')
    if not prof.exists() or not any(prof.iterdir()):
        pytest.skip('EA browser profile missing')
    script = ROOT / 'scripts' / 'diag_ea_session.py'
    if not script.is_file():
        pytest.skip('scripts/diag_ea_session.py missing')
    proc = subprocess.run([sys.executable, str(script)], cwd=str(ROOT), capture_output=True, text=True, timeout=180, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr