import os
import subprocess
import sys
import threading
import time
import warnings

import pytest

import server
from shared import profile_paths, supabase_auth
from shared.subprocess_guard import child_pids_of, terminate_pid_tree

_RUN_MANAGER_THREAD_PREFIXES = ("run-worker", "run-watchdog", "run-kill", "run-launch-")


@pytest.fixture(autouse=True, scope="session")
def _protect_real_profile_store():
    real_index = profile_paths.INDEX_FILE
    real_profiles_dir = profile_paths.PROFILES_DIR
    index_bytes = real_index.read_bytes() if real_index.is_file() else None
    baseline_dirs = {p.name for p in real_profiles_dir.iterdir() if p.is_dir()} if real_profiles_dir.is_dir() else set()
    yield
    if real_profiles_dir.is_dir():
        for child in list(real_profiles_dir.iterdir()):
            if child.is_dir() and child.name not in baseline_dirs:
                import shutil

                warnings.warn(f"test leaked profile dir into real store: {child.name!r}; removing", stacklevel=2)
                shutil.rmtree(child, ignore_errors=True)
    if index_bytes is not None and real_index.is_file():
        if real_index.read_bytes() != index_bytes:
            warnings.warn("test mutated the real profiles/index.json; restoring snapshot", stacklevel=2)
            real_index.write_bytes(index_bytes)


@pytest.fixture(autouse=True)
def _stub_os_keyring_on_macos(monkeypatch):
    if sys.platform != "darwin":
        return
    store = {}

    class _KeyringErrors:
        class KeyringError(Exception):
            pass

        class PasswordDeleteError(KeyringError):
            pass

    class _FakeKeyring:
        errors = _KeyringErrors()

        @staticmethod
        def get_password(service, account):
            return store.get((service, account))

        @staticmethod
        def set_password(service, account, password):
            store[service, account] = password

        @staticmethod
        def delete_password(service, account):
            store.pop((service, account), None)

    monkeypatch.setitem(sys.modules, "keyring", _FakeKeyring())


def _pid_alive(pid):
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _run_manager_threads():
    return [t for t in threading.enumerate() if t.name.startswith(_RUN_MANAGER_THREAD_PREFIXES) and t.is_alive()]


def _cleanup_leaks(*, baseline_threads, baseline_children):
    leaked_threads = [t for t in _run_manager_threads() if t.name not in baseline_threads]
    for t in leaked_threads:
        warnings.warn(f"leaked RunManager thread after test: {t.name!r} (daemon={t.daemon})", stacklevel=2)
    leftover_children = child_pids_of() - baseline_children
    for pid in sorted(leftover_children):
        warnings.warn(f"leaked child process after test: pid={pid}", stacklevel=2)
        terminate_pid_tree(pid)


@pytest.fixture(autouse=True)
def _default_supabase_auth_off(monkeypatch):
    monkeypatch.delenv("BAKLOG_SUPABASE_URL", raising=False)
    monkeypatch.delenv("BAKLOG_SUPABASE_ANON_KEY", raising=False)
    monkeypatch.delenv("BAKLOG_SUPABASE_JWT_SECRET", raising=False)
    monkeypatch.delenv("BAKLOG_AUTH_DISABLED", raising=False)
    monkeypatch.delenv("BAKLOG_LOCAL_PROFILES", raising=False)
    monkeypatch.delenv("BAKLOG_PROFILE", raising=False)
    monkeypatch.delenv("BAKLOG_PLAN", raising=False)
    supabase_auth.reset_jwks_client_for_tests()


@pytest.fixture(autouse=True)
def _reset_auth_sessions():
    try:
        from auth import manager as auth_manager
    except Exception:
        yield
        return
    with auth_manager._sessions_lock:
        auth_manager._active_sessions.clear()
    yield
    with auth_manager._sessions_lock:
        auth_manager._active_sessions.clear()


@pytest.fixture(autouse=True)
def _detect_thread_and_child_leaks(request):
    if request.node.get_closest_marker("no_leak_check"):
        yield
        return
    baseline_threads = {t.name for t in _run_manager_threads()}
    baseline_children = child_pids_of()
    yield

    def _suspected_leak():
        threads = [t for t in _run_manager_threads() if t.name not in baseline_threads]
        children = {p for p in child_pids_of() if _pid_alive(p)} - baseline_children
        return (children, threads)

    leaked_threads = [t for t in _run_manager_threads() if t.name not in baseline_threads]
    if not leaked_threads:
        leftover_children = {p for p in child_pids_of() if _pid_alive(p)} - baseline_children
        if not leftover_children:
            return
    time.sleep(0.25)
    leftover_children, leaked_threads = _suspected_leak()
    if not leftover_children and (not leaked_threads):
        return
    _cleanup_leaks(baseline_threads=baseline_threads, baseline_children=baseline_children)


@pytest.fixture()
def run_manager(tmp_path, monkeypatch):
    runs_dir = tmp_path / "runs"

    def _runs_dir_fn(*, profile_id=None):
        return runs_dir

    monkeypatch.setattr("shared.profile_paths.runs_dir", _runs_dir_fn)
    monkeypatch.setattr(server, "runs_dir", _runs_dir_fn)
    monkeypatch.setattr(server, "RUNS_DIR", runs_dir)
    monkeypatch.setattr(server, "ACTIVE_RUNS_FILE", runs_dir / "active.json")
    monkeypatch.setattr(server, "RUN_HISTORY_FILE", runs_dir / "history.json")
    monkeypatch.setattr(server, "QUEUE_FILE", runs_dir / "queue.json")
    mgr = server.RunManager(runs_dir=runs_dir, enable_watchdog=False)
    try:
        yield mgr
    finally:
        try:
            mgr.force_reset()
        except Exception:
            pass
        try:
            mgr.shutdown()
        except Exception:
            pass
        mgr.join_threads(timeout=5.0)


@pytest.mark.no_leak_check
def test_leak_detector_cleans_stray_thread():
    started = threading.Event()

    def _block():
        started.set()
        time.sleep(30)

    t = threading.Thread(target=_block, name="run-launch-leak-selfcheck", daemon=True)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        t.start()
        assert started.wait(timeout=2.0)
        _cleanup_leaks(baseline_threads=set(), baseline_children=set())
    assert any(("leaked RunManager thread" in str(w.message) for w in caught))


@pytest.mark.no_leak_check
def test_leak_detector_cleans_child_process():
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            _cleanup_leaks(baseline_threads=set(), baseline_children=set())
        assert any(("leaked child process" in str(w.message) for w in caught))
    finally:
        if proc.poll() is None:
            terminate_pid_tree(proc.pid)
        proc.wait(timeout=5)
