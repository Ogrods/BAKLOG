import json
import os
import queue
import subprocess
import sys
import threading
import time
import uuid
from collections import deque

from shared.dev_server_pids import pid_alive as _pid_alive
from shared.dev_server_pids import terminate_pid as _terminate_pid_native
from shared.install_paths import data_root
from shared.log_redact import redact_log_line as _redact_log_line
from shared.profile_paths import get_active_profile_id
from shared.profile_paths import runs_dir as profile_runs_dir
from shared.subprocess_guard import popen_fetcher

MAX_HISTORY = 200
MAX_LINES_PER_RUN = 25000
STALL_FIRST_NOTICE_SEC = 60
STALL_REPEAT_SEC = 60
STALL_POLL_SEC = 1.0
SILENT_STALL_KILL_SEC = 180
TERMINATE_GRACE_SEC = 5
CANCEL_STUCK_GRACE_SEC = TERMINATE_GRACE_SEC + 2
SWITCH_CANCEL_WAIT_SEC = 2 * TERMINATE_GRACE_SEC
WATCHDOG_INTERVAL_SEC = 3.0
LAUNCH_TIMEOUT_SEC = 30
STUCK_NO_PROC_GRACE_SEC = LAUNCH_TIMEOUT_SEC + 15
_IN_FLIGHT_STATUSES = frozenset({"queued", "launching", "running", "cancelling"})
_runs_file_lock = threading.Lock()


def _server():
    import server as mod

    return mod


def _fetchers():
    return _server().FETCHERS


def _internal_jobs():
    return _server().INTERNAL_JOBS


def _max_run_seconds_for_key(key):
    return _server()._max_run_seconds_for_key(key)


def _internal_job_argv(spec, extra_args):
    return _server()._internal_job_argv(spec, extra_args)


def _run_cfg(name, default):
    return getattr(_server(), name, default)


def _active_profile_id():
    getter = getattr(_server(), "get_active_profile_id", None)
    if callable(getter):
        return str(getter())
    return get_active_profile_id()


def _popen_fetcher(*args, **kwargs):
    pop = getattr(_server(), "popen_fetcher", None)
    if pop is not None:
        return pop(*args, **kwargs)
    return popen_fetcher(*args, **kwargs)


def _active_runs_path():
    path = getattr(_server(), "ACTIVE_RUNS_FILE", None)
    if path is not None:
        return path
    return profile_runs_dir() / "active.json"


def _queue_path():
    path = getattr(_server(), "QUEUE_FILE", None)
    if path is not None:
        return path
    return profile_runs_dir() / "queue.json"


def _run_history_path():
    path = getattr(_server(), "RUN_HISTORY_FILE", None)
    if path is not None:
        return path
    return profile_runs_dir() / "history.json"


def _terminate_pid(pid):
    override = getattr(_server(), "_terminate_pid", None)
    if override is not None:
        override(pid)
        return
    _terminate_pid_native(pid)


def _kill_pids_async(pids):
    override = getattr(_server(), "_kill_pids_async", None)
    if override is not None:
        override(pids)
        return
    unique = list(dict.fromkeys((p for p in pids if p > 0)))
    if not unique:
        return

    def _work():
        for pid in unique:
            _terminate_pid(pid)

    threading.Thread(target=_work, name="run-kill", daemon=True).start()


def _read_json_file(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json_atomic(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _read_active_runs():
    with _runs_file_lock:
        data = _read_json_file(_active_runs_path(), {"runs": []})
    runs = data.get("runs") if isinstance(data, dict) else []
    return runs if isinstance(runs, list) else []


def _write_active_runs(runs):
    with _runs_file_lock:
        _write_json_atomic(_active_runs_path(), {"runs": runs})


def _run_id_active_on_disk(run_id):
    return any((entry.get("id") == run_id for entry in _read_active_runs()))


def _fetcher_is_enrich(key):
    return _fetchers().get(key, {}).get("group") == "enrich"


def _filter_runs_by_lane(runs, lane):
    if lane == "fetcher":
        return [r for r in runs if not r._internal and (not r._enrich)]
    if lane == "enrich":
        return [r for r in runs if r._enrich]
    if lane == "internal":
        return [r for r in runs if r._internal]
    return list(runs)


def _load_durable_queue():
    with _runs_file_lock:
        data = _read_json_file(_queue_path(), {"runs": []})
    runs = data.get("runs") if isinstance(data, dict) else []
    return runs if isinstance(runs, list) else []


def _save_durable_queue(entries):
    with _runs_file_lock:
        _write_json_atomic(_queue_path(), {"runs": entries})


def _load_run_history_from(path=None):
    hist_path = path or _run_history_path()
    data = _read_json_file(hist_path, [])
    return data if isinstance(data, list) else []


def _load_run_history():
    return _load_run_history_from(_run_history_path())


def _save_run_history_to(path, entries):
    _write_json_atomic(path, entries[:MAX_HISTORY])


def _save_run_history(entries):
    _save_run_history_to(_run_history_path(), entries)


class Run:
    __slots__ = (
        "id",
        "key",
        "label",
        "status",
        "started_at",
        "ended_at",
        "exit_code",
        "lines",
        "_lock",
        "_listeners",
        "_finished",
        "_proc",
        "cancelled",
        "refresh",
        "_log_path",
        "_runs_dir",
        "profile_id",
        "_cancelling_since",
        "_no_proc_since",
        "_history_note",
        "_next_seq",
        "_total_lines",
        "_finalized",
        "_internal",
        "_internal_extra_args",
        "_enrich",
    )

    def __init__(
        self,
        key,
        refresh=False,
        *,
        runs_dir_path=None,
        runs_dir=None,
        profile_id=None,
        internal=False,
        enrich=False,
        extra_args=None,
    ):
        if internal:
            if key not in _internal_jobs():
                raise KeyError(key)
            spec = _internal_jobs()[key]
        else:
            spec = _fetchers()[key]
        self.id = uuid.uuid4().hex[:12]
        self.key = key
        self.profile_id = profile_id or _active_profile_id()
        self.label = spec["label"]
        self.refresh = refresh
        self._internal = internal
        self._enrich = enrich and (not internal)
        self._internal_extra_args = list(extra_args or [])
        self.status = "queued"
        self.started_at = None
        self.ended_at = None
        self.exit_code = None
        self.cancelled = False
        self._finalized = False
        self._proc = None
        resolved_runs_dir = runs_dir_path if runs_dir_path is not None else runs_dir
        self._runs_dir = resolved_runs_dir if resolved_runs_dir is not None else profile_runs_dir()
        self._runs_dir.mkdir(parents=True, exist_ok=True)
        self._log_path = self._runs_dir / f"{self.id}.jsonl"
        self.lines = deque(maxlen=MAX_LINES_PER_RUN)
        self._next_seq = 0
        self._total_lines = 0
        self._lock = threading.Lock()
        self._listeners = set()
        self._finished = threading.Event()
        self._cancelling_since = None
        self._no_proc_since = None
        self._history_note = None
        self._restore_seq_from_disk()

    def _restore_seq_from_disk(self):
        if not self._log_path.exists():
            return
        max_seq = 0
        count = 0
        fallback = 0
        try:
            with self._log_path.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    count += 1
                    msg = json.loads(line)
                    seq = msg.get("seq")
                    if seq is None:
                        fallback += 1
                        seq = fallback
                    max_seq = max(max_seq, int(seq))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[runs] log scan failed {self.id}: {exc!r}", file=sys.stderr)
            return
        self._next_seq = max_seq
        self._total_lines = count

    def to_summary(self):
        summary = {
            "id": self.id,
            "key": self.key,
            "label": self.label,
            "status": self.status,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "exit_code": self.exit_code,
            "line_count": self._total_lines,
        }
        if self.exit_code == 4:
            summary["failure_kind"] = "auth"
        if self._history_note:
            summary["note"] = self._history_note
        summary["profile_id"] = self.profile_id
        if self._enrich:
            summary["lane"] = "enrich"
        elif self._internal:
            summary["lane"] = "internal"
        else:
            summary["lane"] = "fetcher"
        if not self._internal:
            summary["group"] = _fetchers().get(self.key, {}).get("group")
        return summary

    def add_line(self, stream, text):
        with self._lock:
            self._next_seq += 1
            self._total_lines += 1
            seq = self._next_seq
            msg = {"seq": seq, "t": time.time(), "stream": stream, "text": _redact_log_line(text)}
            self.lines.append(msg)
            try:
                with self._log_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(msg, ensure_ascii=False) + "\n")
            except OSError as exc:
                print(f"[runs] log write failed {self.id}: {exc!r}", file=sys.stderr)
            for q in list(self._listeners):
                try:
                    q.put_nowait(("line", msg))
                except queue.Full:
                    self._listeners.discard(q)

    def broadcast(self, event, data):
        with self._lock:
            for q in list(self._listeners):
                try:
                    q.put_nowait((event, data))
                except queue.Full:
                    self._listeners.discard(q)

    def replay_lines(self, since=0):
        since = max(0, int(since))

        def _with_seq(messages):
            out = []
            fallback = 0
            for msg in messages:
                seq = msg.get("seq")
                if seq is None:
                    fallback += 1
                    msg = {**msg, "seq": fallback}
                out.append(msg)
            return [m for m in out if int(m.get("seq", 0)) > since]

        if self._log_path.exists():
            replay = []
            try:
                with self._log_path.open(encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        replay.append(json.loads(line))
                return _with_seq(replay)
            except (OSError, json.JSONDecodeError) as exc:
                print(f"[runs] log read failed {self.id}: {exc!r}", file=sys.stderr)
        with self._lock:
            return _with_seq(list(self.lines))

    def attach_listener(self, since=0):
        q = queue.Queue(maxsize=1024)
        with self._lock:
            replay = self.replay_lines(since)
            done = self._finished.is_set()
            if not done:
                self._listeners.add(q)
        return (q, replay, done)

    def detach_listener(self, q):
        with self._lock:
            self._listeners.discard(q)

    def mark_finished(self):
        self._finished.set()

    def argv(self):
        if self._internal:
            return _internal_job_argv(_internal_jobs()[self.key], self._internal_extra_args)
        spec = _fetchers()[self.key]
        argv = list(spec["argv"])
        if self.refresh:
            for arg in spec.get("refreshArgs") or []:
                if arg not in argv:
                    argv.append(arg)
        return argv

    def cancel(self):
        proc = None
        notify_done = False
        notify_cancelling = False
        with self._lock:
            if self.status in ("done", "failed", "cancelled") or self._finished.is_set():
                return (False, [])
            if self.status == "queued":
                self.status = "cancelled"
                self.exit_code = -1
                self.ended_at = time.time()
                notify_done = True
            elif self.status in ("launching", "running"):
                self.cancelled = True
                proc = self._proc
                if proc is None or proc.poll() is not None:
                    self.status = "cancelled"
                    self.exit_code = -1
                    self.ended_at = time.time()
                    notify_done = True
                else:
                    self.status = "cancelling"
                    self._cancelling_since = time.monotonic()
                    notify_cancelling = True
            elif self.status == "cancelling":
                return (False, [])
            else:
                return (False, [])
        if notify_cancelling:
            self.broadcast("status", {"status": self.status, "started_at": self.started_at})
        if notify_done:
            self.add_line("stderr", "[server] cancelled before start")
            self.mark_finished()
            self.broadcast(
                "done",
                {
                    "status": self.status,
                    "exit_code": self.exit_code,
                    "started_at": self.started_at,
                    "ended_at": self.ended_at,
                },
            )
            return (True, [])
        pids = []
        if proc is not None and proc.poll() is None and proc.pid:
            pids.append(proc.pid)
        return (True, pids)


class RunManager:
    def __init__(self, runs_dir=None, *, enable_watchdog=True, reap_orphans=None, restore_durable=True):
        self._runs_dir = runs_dir if runs_dir is not None else profile_runs_dir()
        self._runs_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._queue = queue.Queue()
        self._enrich_queue = queue.Queue()
        self._internal_queue = queue.Queue()
        self._pending = []
        self._history = deque(
            _load_run_history_from(self._runs_dir / "history.json")[-MAX_HISTORY:], maxlen=MAX_HISTORY
        )
        self._active = None
        self._enrich_active = None
        self._internal_active = None
        self._runs_by_id = {}
        self._last_queue_kick_at = 0.0
        self._watchdog_stop = threading.Event()
        if reap_orphans if reap_orphans is not None else runs_dir is not None:
            self._reap_orphan_processes()
        self._start_worker_thread()
        self._watchdog_thread = None
        if enable_watchdog:
            self._watchdog_thread = threading.Thread(target=self._watchdog_loop, name="run-watchdog", daemon=True)
            self._watchdog_thread.start()
        if restore_durable:
            self._restore_durable_queue()

    def _start_worker_thread(self):
        self._worker_thread = threading.Thread(
            target=self._worker_loop, args=("fetcher",), name="run-worker", daemon=True
        )
        self._worker_thread.start()
        self._enrich_worker_thread = threading.Thread(
            target=self._worker_loop, args=("enrich",), name="run-worker-enrich", daemon=True
        )
        self._enrich_worker_thread.start()
        self._internal_worker_thread = threading.Thread(
            target=self._worker_loop, args=("internal",), name="run-worker-internal", daemon=True
        )
        self._internal_worker_thread.start()

    def _ensure_worker_thread(self):
        if not self._worker_thread.is_alive():
            print("[runs] fetcher worker thread died — restarting", file=sys.stderr, flush=True)
            self._worker_thread = threading.Thread(
                target=self._worker_loop, args=("fetcher",), name="run-worker", daemon=True
            )
            self._worker_thread.start()
        enrich = getattr(self, "_enrich_worker_thread", None)
        if enrich is None or not enrich.is_alive():
            print("[runs] enrich worker thread died — restarting", file=sys.stderr, flush=True)
            self._enrich_worker_thread = threading.Thread(
                target=self._worker_loop, args=("enrich",), name="run-worker-enrich", daemon=True
            )
            self._enrich_worker_thread.start()
        internal = getattr(self, "_internal_worker_thread", None)
        if internal is None or not internal.is_alive():
            print("[runs] internal worker thread died — restarting", file=sys.stderr, flush=True)
            self._internal_worker_thread = threading.Thread(
                target=self._worker_loop, args=("internal",), name="run-worker-internal", daemon=True
            )
            self._internal_worker_thread.start()

    def _resync_stalled_queue(self):
        return self._resync_lane("fetcher") + self._resync_lane("enrich") + self._resync_lane("internal")

    def _lane_queue(self, lane):
        if lane == "internal":
            return self._internal_queue
        if lane == "enrich":
            return self._enrich_queue
        return self._queue

    def _lane_active(self, lane):
        if lane == "internal":
            return self._internal_active
        if lane == "enrich":
            return self._enrich_active
        return self._active

    def _set_lane_active(self, lane, run):
        if lane == "internal":
            self._internal_active = run
        elif lane == "enrich":
            self._enrich_active = run
        else:
            self._active = run

    def _run_in_lane(self, run, lane):
        if lane == "internal":
            return run._internal
        if lane == "enrich":
            return run._enrich
        return not run._internal and (not run._enrich)

    def _resync_lane(self, lane):
        lane_queue = self._lane_queue(lane)
        to_put = []
        with self._lock:
            active = self._lane_active(lane)
            if active is not None and active._finished.is_set():
                self._set_lane_active(lane, None)
                active = None
            if active is not None:
                return 0
            if lane_queue.qsize() > 0:
                return 0
            for r in self._pending:
                if not self._run_in_lane(r, lane):
                    continue
                if r.status == "queued" and (not r._finished.is_set()):
                    to_put.append(r)
        for r in to_put:
            lane_queue.put(r)
        if to_put:
            keys = ", ".join((r.key for r in to_put))
            print(f"[runs] re-queued {len(to_put)} stalled {lane} run(s): {keys}", file=sys.stderr, flush=True)
        return len(to_put)

    def _kick_queue_if_stalled(self):
        self._ensure_worker_thread()
        self._resync_stalled_queue()

    def _kick_queue_if_stalled_throttled(self):
        now = time.monotonic()
        if now - self._last_queue_kick_at < 1.0:
            return
        self._last_queue_kick_at = now
        self._kick_queue_if_stalled()

    def _watchdog_loop(self):
        while not self._watchdog_stop.wait(_run_cfg("WATCHDOG_INTERVAL_SEC", WATCHDOG_INTERVAL_SEC)):
            try:
                self._kick_queue_if_stalled()
                self._force_finalize_stuck_cancelling()
                self._force_finalize_orphaned_runs()
            except Exception as exc:
                print(f"[runs] watchdog error: {exc!r}", file=sys.stderr, flush=True)

    def _force_finalize_stuck_cancelling(self):
        now = time.monotonic()
        stuck = []
        with self._lock:
            for r in self._pending:
                if (
                    r.status == "cancelling"
                    and r._cancelling_since is not None
                    and (now - r._cancelling_since > _run_cfg("CANCEL_STUCK_GRACE_SEC", CANCEL_STUCK_GRACE_SEC))
                ):
                    stuck.append(r)
            for active in (self._active, self._enrich_active, self._internal_active):
                if (
                    active
                    and active.status == "cancelling"
                    and (active._cancelling_since is not None)
                    and (now - active._cancelling_since > _run_cfg("CANCEL_STUCK_GRACE_SEC", CANCEL_STUCK_GRACE_SEC))
                    and (active not in stuck)
                ):
                    stuck.append(active)
        for run in stuck:
            pids = self._collect_pids_for_run(run, [])
            if pids:
                _kill_pids_async(pids)
            with run._lock:
                if not run._finished.is_set():
                    run.status = "cancelled"
                    run.exit_code = -1
                    if run.ended_at is None:
                        run.ended_at = time.time()
            if not run._finished.is_set():
                run.mark_finished()
                run.broadcast(
                    "done",
                    {
                        "status": run.status,
                        "exit_code": run.exit_code,
                        "started_at": run.started_at,
                        "ended_at": run.ended_at,
                    },
                )
            self._finalize_run(run)

    def _run_has_live_process(self, run):
        if run._proc is not None and run._proc.poll() is None:
            return True
        for entry in _read_active_runs():
            if entry.get("id") == run.id:
                pid = int(entry.get("pid") or 0)
                if _pid_alive(pid):
                    return True
        return False

    def _force_finalize_orphaned_runs(self):
        now = time.monotonic()
        stuck = []
        with self._lock:
            candidates = []
            for active in (self._active, self._enrich_active, self._internal_active):
                if active and active.status in ("launching", "running") and (not active._finished.is_set()):
                    candidates.append(active)
            for r in self._pending:
                if r.status in ("launching", "running") and (not r._finished.is_set()) and (r not in candidates):
                    candidates.append(r)
            for run in candidates:
                if self._run_has_live_process(run):
                    run._no_proc_since = None
                    continue
                if run._no_proc_since is None:
                    run._no_proc_since = now
                    continue
                if now - run._no_proc_since > _run_cfg("STUCK_NO_PROC_GRACE_SEC", STUCK_NO_PROC_GRACE_SEC):
                    stuck.append(run)
        for run in stuck:
            pids = self._collect_pids_for_run(run, [])
            if pids:
                _kill_pids_async(pids)
            with run._lock:
                if not run._finished.is_set():
                    run.status = "failed"
                    run.exit_code = -1
                    if run.ended_at is None:
                        run.ended_at = time.time()
                    run._history_note = "force-finalized: no live subprocess (worker stalled)"
            if not run._finished.is_set():
                run.add_line(
                    "stderr", "[server] no live subprocess — force-finalizing stalled run so the queue can advance"
                )
                run.mark_finished()
                run.broadcast(
                    "done",
                    {
                        "status": run.status,
                        "exit_code": run.exit_code,
                        "started_at": run.started_at,
                        "ended_at": run.ended_at,
                    },
                )
            self._finalize_run(run)

    def _collect_pids_for_run(self, run, proc_pids):
        pids = list(proc_pids)
        if run._proc is not None and run._proc.poll() is None and run._proc.pid:
            if run._proc.pid not in pids:
                pids.append(run._proc.pid)
        for entry in _read_active_runs():
            if entry.get("id") == run.id:
                pid = int(entry.get("pid") or 0)
                if pid > 0 and pid not in pids:
                    pids.append(pid)
        return pids

    def _complete_cancel_after_kill(self, run):
        proc = run._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.wait(timeout=_run_cfg("TERMINATE_GRACE_SEC", TERMINATE_GRACE_SEC))
            except Exception:
                pass
        should_finish = False
        with run._lock:
            if not run._finished.is_set():
                run.status = "cancelled"
                run.exit_code = -1
                if run.ended_at is None:
                    run.ended_at = time.time()
                should_finish = True
        if should_finish:
            run.mark_finished()
            run.broadcast(
                "done",
                {
                    "status": run.status,
                    "exit_code": run.exit_code,
                    "started_at": run.started_at,
                    "ended_at": run.ended_at,
                },
            )
        self._finalize_run(run)

    def stream_terminal_summary(self, run_id):
        with self._lock:
            for h in self._history:
                if h.get("id") == run_id:
                    return h
        hist_file = self._runs_dir / "history.json"
        for h in _load_run_history_from(hist_file):
            if h.get("id") == run_id:
                return h
        return None

    def rebind_profile_paths(self):
        self._runs_dir = profile_runs_dir()
        self._runs_dir.mkdir(parents=True, exist_ok=True)
        active_pid = _active_profile_id()
        with self._lock:
            self._history = deque(
                _load_run_history_from(self._runs_dir / "history.json")[-MAX_HISTORY:], maxlen=MAX_HISTORY
            )
            self._runs_by_id = {rid: run for rid, run in self._runs_by_id.items() if run.profile_id == active_pid}
            self._pending = [r for r in self._pending if r.profile_id == active_pid]
            if self._active is not None and self._active.profile_id != active_pid:
                self._active = None
            if self._enrich_active is not None and self._enrich_active.profile_id != active_pid:
                self._enrich_active = None
            if self._internal_active is not None and self._internal_active.profile_id != active_pid:
                self._internal_active = None

    def _persist_queue(self):
        with self._lock:
            entries = [{"id": r.id, "key": r.key, "refresh": r.refresh} for r in self._pending if r.status == "queued"]
        _save_durable_queue(entries)

    def _latest_history_for_key(self, key):
        with self._lock:
            for h in self._history:
                if h.get("key") == key:
                    return h
        return None

    def _restore_durable_queue(self):
        history_ids = {h.get("id") for h in self._history}
        restored = 0
        for entry in _load_durable_queue():
            key = entry.get("key")
            if not key or key not in _fetchers():
                continue
            if entry.get("id") in history_ids:
                continue
            latest = self._latest_history_for_key(key)
            if latest and latest.get("status") == "done":
                continue
            try:
                self.submit(key, refresh=bool(entry.get("refresh")))
                restored += 1
            except ValueError:
                break
        if restored:
            print(f"[runs] restored {restored} queued run(s) from durable queue", file=sys.stderr)

    def _prune_runs_by_id(self):
        with self._lock:
            if len(self._runs_by_id) <= MAX_HISTORY:
                return
            keep_ids = {r.id for r in self._pending}
            keep_ids.update((h.get("id") for h in self._history if h.get("id")))
            for rid in list(self._runs_by_id):
                if rid not in keep_ids:
                    del self._runs_by_id[rid]

    def _append_history(self, summary, *, profile_id):
        if profile_id == _active_profile_id():
            hist_file = _run_history_path()
        else:
            hist_file = profile_runs_dir(profile_id=profile_id) / "history.json"
        entries = _load_run_history_from(hist_file)
        entries.insert(0, summary)
        _save_run_history_to(hist_file, entries)
        with self._lock:
            if profile_id == _active_profile_id():
                self._history.appendleft(summary)
                while len(self._history) > MAX_HISTORY:
                    self._history.pop()

    def _register_pending_run(self, run):
        entry = {
            "id": run.id,
            "pid": 0,
            "key": run.key,
            "label": run.label,
            "started_at": run.started_at or time.time(),
        }
        active = [e for e in _read_active_runs() if e.get("id") != run.id]
        active.append(entry)
        _write_active_runs(active)

    def _register_active_process(self, run, pid):
        entry = {"id": run.id, "pid": pid, "key": run.key, "label": run.label, "started_at": run.started_at}
        active = [e for e in _read_active_runs() if e.get("id") != run.id]
        active.append(entry)
        _write_active_runs(active)

    def _unregister_active_process(self, run_id):
        active = [e for e in _read_active_runs() if e.get("id") != run_id]
        _write_active_runs(active)

    def _wait_or_kill_proc(self, run, proc):
        grace = _run_cfg("TERMINATE_GRACE_SEC", TERMINATE_GRACE_SEC)
        try:
            proc.wait(timeout=grace)
            return
        except Exception:
            pass
        if proc.poll() is not None or not proc.pid:
            return
        _terminate_pid(proc.pid)
        try:
            proc.wait(timeout=grace)
            return
        except Exception:
            pass
        if proc.poll() is None:
            run.add_line(
                "stderr", f"[server] PID {proc.pid} did not exit after kill; abandoning it and advancing the queue"
            )

    def _reap_orphan_processes(self):
        for entry in _read_active_runs():
            pid = int(entry.get("pid") or 0)
            if _pid_alive(pid):
                _terminate_pid(pid)
            summary = {
                "id": entry.get("id", "?"),
                "key": entry.get("key", "?"),
                "label": entry.get("label", "?"),
                "status": "failed",
                "started_at": entry.get("started_at"),
                "ended_at": time.time(),
                "exit_code": -1,
                "line_count": 0,
                "note": "orphaned — previous server stopped while this fetcher was running",
            }
            self._append_history(summary, profile_id=_active_profile_id())
        _write_active_runs([])

    def shutdown(self):
        self._watchdog_stop.set()
        with self._lock:
            pending = list(self._pending)
            actives = [self._active, self._enrich_active, self._internal_active]
        kill_pids = []
        for run in pending:
            changed, pids = run.cancel()
            if changed:
                kill_pids.extend(self._collect_pids_for_run(run, pids))
        for active in actives:
            if active is not None:
                changed, pids = active.cancel()
                if changed:
                    kill_pids.extend(self._collect_pids_for_run(active, pids))
        if kill_pids:
            for pid in dict.fromkeys(kill_pids):
                _terminate_pid(pid)
        _write_active_runs([])
        _save_durable_queue([])
        for lane_queue in (self._queue, self._enrich_queue, self._internal_queue):
            try:
                lane_queue.put_nowait(None)
            except Exception:
                pass
        self.join_threads(timeout=5.0)

    def join_threads(self, timeout=5.0):
        self._watchdog_stop.set()
        wt = getattr(self, "_watchdog_thread", None)
        if wt is not None and wt.is_alive():
            wt.join(timeout=timeout)
        if self._worker_thread.is_alive():
            self._worker_thread.join(timeout=timeout)
        enrich = getattr(self, "_enrich_worker_thread", None)
        if enrich is not None and enrich.is_alive():
            enrich.join(timeout=timeout)
        internal = getattr(self, "_internal_worker_thread", None)
        if internal is not None and internal.is_alive():
            internal.join(timeout=timeout)

    def submit(self, key, *, refresh=False):
        if key not in _fetchers():
            raise KeyError(key)
        is_enrich = _fetcher_is_enrich(key)

        def _in_lane(r):
            if is_enrich:
                return r._enrich
            return not r._internal and (not r._enrich)

        with self._lock:
            active = self._enrich_active if is_enrich else self._active
            if active and active.key == key and (active.status in _IN_FLIGHT_STATUSES):
                raise ValueError(f"{key} already queued or running")
            if any((_in_lane(r) and r.key == key and (r.status in _IN_FLIGHT_STATUSES) for r in self._pending)):
                raise ValueError(f"{key} already queued or running")
            in_flight = sum((1 for r in self._pending if _in_lane(r) and r.status in _IN_FLIGHT_STATUSES))
            if active and active.status in _IN_FLIGHT_STATUSES and (active not in self._pending):
                in_flight += 1
            if in_flight >= 1:
                lane_label = "enrich" if is_enrich else "fetch"
                raise ValueError(
                    f"queue full — a {lane_label} is already running; wait for it to finish before starting another"
                )
            profile_id = _active_profile_id()
            run = Run(
                key,
                refresh=refresh,
                runs_dir_path=profile_runs_dir(profile_id=profile_id),
                profile_id=profile_id,
                enrich=is_enrich,
            )
            self._pending.append(run)
            self._runs_by_id[run.id] = run
            (self._enrich_queue if is_enrich else self._queue).put(run)
        self._register_pending_run(run)
        self._persist_queue()
        self._ensure_worker_thread()
        return run

    def submit_internal(self, key, extra_args=None, *, profile_id=None):
        if key not in _internal_jobs():
            raise KeyError(key)
        with self._lock:
            active = self._internal_active
            if active and active.key == key and (active.status in _IN_FLIGHT_STATUSES):
                raise ValueError(f"{key} already queued or running")
            if any((r._internal and r.key == key and (r.status in _IN_FLIGHT_STATUSES) for r in self._pending)):
                raise ValueError(f"{key} already queued or running")
            in_flight = sum((1 for r in self._pending if r._internal and r.status in _IN_FLIGHT_STATUSES))
            if active and active.status in _IN_FLIGHT_STATUSES and (active not in self._pending):
                in_flight += 1
            if in_flight >= 1:
                raise ValueError("an admin job is already running; wait for it to finish before starting another")
            pid = profile_id or _active_profile_id()
            run = Run(
                key,
                runs_dir_path=profile_runs_dir(profile_id=pid),
                profile_id=pid,
                internal=True,
                extra_args=extra_args or [],
            )
            self._pending.append(run)
            self._runs_by_id[run.id] = run
            self._internal_queue.put(run)
        self._register_pending_run(run)
        self._persist_queue()
        self._ensure_worker_thread()
        return run

    def cancel(self, run_id):
        with self._lock:
            run = self._runs_by_id.get(run_id)
            if run is None:
                return (None, "not_found")
            if run.status in ("done", "failed", "cancelled") or run._finished.is_set():
                return (None, "already_finished")
        changed, proc_pids = run.cancel()
        if not changed:
            return (None, "already_finished")
        pids = self._collect_pids_for_run(run, proc_pids)
        with self._lock:
            if run in self._pending:
                self._pending.remove(run)
        self._persist_queue()
        if run._finished.is_set():
            self._finalize_run(run)
        elif run.status == "cancelling":
            if pids:
                _kill_pids_async(pids)
            self._schedule_cancel_completion(run)
        return (run, None)

    def _schedule_cancel_completion(self, run):
        if self._worker_thread.is_alive():
            threading.Thread(
                target=self._complete_cancel_after_kill, args=(run,), name=f"run-cancel-{run.id}", daemon=True
            ).start()
        else:
            self._complete_cancel_after_kill(run)

    def cancel_all(self, *, profile_id=None, lane=None):
        with self._lock:
            targets = [r for r in self._pending if r.status in _IN_FLIGHT_STATUSES]
            for active in (self._active, self._enrich_active, self._internal_active):
                if active and active.status in _IN_FLIGHT_STATUSES and (active not in targets):
                    targets.append(active)
        targets = _filter_runs_by_lane(targets, lane)
        if profile_id is not None:
            targets = [r for r in targets if r.profile_id == profile_id]
        all_pids = []
        summaries = []
        to_finalize_now = []
        to_complete_async = []
        for run in targets:
            changed, proc_pids = run.cancel()
            if not changed:
                continue
            all_pids.extend(self._collect_pids_for_run(run, proc_pids))
            with self._lock:
                if run in self._pending:
                    self._pending.remove(run)
            if run._finished.is_set():
                to_finalize_now.append(run)
            elif run.status == "cancelling":
                to_complete_async.append(run)
            summaries.append(run.to_summary())
        self._persist_queue()
        if all_pids:
            _kill_pids_async(all_pids)
        for run in to_finalize_now:
            self._finalize_run(run)
        for run in to_complete_async:
            self._schedule_cancel_completion(run)
        return summaries

    def force_reset(self, *, profile_id=None, lane=None):
        with self._lock:
            targets = [r for r in self._pending if r.status in _IN_FLIGHT_STATUSES]
            for active in (self._active, self._enrich_active, self._internal_active):
                if active and active.status in _IN_FLIGHT_STATUSES and (active not in targets):
                    targets.append(active)
        targets = _filter_runs_by_lane(targets, lane)
        if profile_id is not None:
            targets = [r for r in targets if r.profile_id == profile_id]
        all_pids = []
        if lane is None:
            for entry in _read_active_runs():
                pid = int(entry.get("pid") or 0)
                if pid <= 0:
                    continue
                if profile_id is not None and str(entry.get("profile_id") or "") != str(profile_id):
                    continue
                all_pids.append(pid)
        for run in targets:
            run.cancelled = True
            with run._lock:
                if run.status in _IN_FLIGHT_STATUSES and (not run._finished.is_set()):
                    run.status = "cancelled"
                    run.exit_code = -1
                    run.ended_at = time.time()
            all_pids.extend(self._collect_pids_for_run(run, []))
        target_ids = {run.id for run in targets}
        drains = []
        if lane in (None, "fetcher"):
            drains.append(self._queue)
        if lane in (None, "enrich"):
            drains.append(self._enrich_queue)
        if lane in (None, "internal"):
            drains.append(self._internal_queue)
        for drain in drains:
            while True:
                try:
                    drain.get_nowait()
                except queue.Empty:
                    break
        with self._lock:
            if lane is None:
                self._pending.clear()
                self._active = None
                self._enrich_active = None
                self._internal_active = None
            else:
                self._pending = [r for r in self._pending if r not in targets]
                if lane == "fetcher":
                    self._active = None
                elif lane == "enrich":
                    self._enrich_active = None
                elif lane == "internal":
                    self._internal_active = None
        if lane is None:
            _write_active_runs([])
        else:
            _write_active_runs([e for e in _read_active_runs() if e.get("id") not in target_ids])
        _save_durable_queue([])
        if all_pids:
            _kill_pids_async(list(dict.fromkeys(all_pids)))
        summaries = []
        for run in targets:
            if not run._finished.is_set():
                run.mark_finished()
                run.broadcast(
                    "done",
                    {
                        "status": "cancelled",
                        "exit_code": run.exit_code or -1,
                        "started_at": run.started_at,
                        "ended_at": run.ended_at,
                    },
                )
            self._finalize_run(run)
            summaries.append(run.to_summary())
        self._ensure_worker_thread()
        return {"cancelled": summaries, "force": True}

    def _in_flight_targets(self, profile_id=None):
        with self._lock:
            targets = [r for r in self._pending if r.status in _IN_FLIGHT_STATUSES]
            for active in (self._active, self._enrich_active, self._internal_active):
                if active and active.status in _IN_FLIGHT_STATUSES and (active not in targets):
                    targets.append(active)
        if profile_id is not None:
            targets = [r for r in targets if r.profile_id == profile_id]
        return targets

    def has_runs_for_profile(self, profile_id):
        return bool(self._in_flight_targets(profile_id))

    def cancel_all_and_wait(self, timeout=SWITCH_CANCEL_WAIT_SEC):
        targets = self._in_flight_targets()
        cancelled = []
        for run in targets:
            run_obj, err = self.cancel(run.id)
            if run_obj is not None and err is None:
                cancelled.append(run_obj.to_summary())
        deadline = time.monotonic() + timeout
        stragglers = []
        for run in targets:
            remaining = deadline - time.monotonic()
            if remaining > 0:
                run._finished.wait(remaining)
            if not run._finished.is_set():
                stragglers.append(run.to_summary())
        if stragglers:
            ids = ", ".join((s.get("id", "?") for s in stragglers))
            print(
                f"WARN: {len(stragglers)} run(s) still not finished after {timeout}s cancel wait: {ids}",
                file=sys.stderr,
                flush=True,
            )
        return {"cancelled": cancelled, "stragglers": stragglers}

    def get(self, run_id):
        with self._lock:
            return self._runs_by_id.get(run_id)

    def snapshot(self):
        self._kick_queue_if_stalled_throttled()
        with self._lock:
            active = self._active.to_summary() if self._active and self._active.status in _IN_FLIGHT_STATUSES else None
            queued = [
                r.to_summary()
                for r in self._pending
                if not r._internal and (not r._enrich) and (r.status == "queued") and (r is not self._active)
            ]
            enrich_active = (
                self._enrich_active.to_summary()
                if self._enrich_active and self._enrich_active.status in _IN_FLIGHT_STATUSES
                else None
            )
            enrich_queue = [
                r.to_summary()
                for r in self._pending
                if r._enrich and r.status == "queued" and (r is not self._enrich_active)
            ]
            internal_active = (
                self._internal_active.to_summary()
                if self._internal_active and self._internal_active.status in _IN_FLIGHT_STATUSES
                else None
            )
            internal_queue = [
                r.to_summary()
                for r in self._pending
                if r._internal and r.status == "queued" and (r is not self._internal_active)
            ]
            history = list(self._history)
        return {
            "active": active,
            "queue": queued,
            "enrich_active": enrich_active,
            "enrich_queue": enrich_queue,
            "internal_active": internal_active,
            "internal_queue": internal_queue,
            "history": history,
        }

    def _finalize_run(self, run):
        with run._lock:
            if run._finalized:
                return
            run._finalized = True
        if not run._finished.is_set():
            if run.ended_at is None:
                run.ended_at = time.time()
            run.mark_finished()
            run.broadcast(
                "done",
                {
                    "status": run.status,
                    "exit_code": run.exit_code,
                    "started_at": run.started_at,
                    "ended_at": run.ended_at,
                },
            )
        with self._lock:
            if self._active is run:
                self._active = None
            if self._enrich_active is run:
                self._enrich_active = None
            if self._internal_active is run:
                self._internal_active = None
            if run in self._pending:
                self._pending.remove(run)
        self._unregister_active_process(run.id)
        self._append_history(run.to_summary(), profile_id=run.profile_id)
        self._persist_queue()
        self._prune_runs_by_id()

    def _worker_loop(self, lane="fetcher"):
        lane_queue = self._lane_queue(lane)
        while True:
            try:
                run = lane_queue.get()
                if run is None:
                    return
                if not run._finished.is_set():
                    with self._lock:
                        self._set_lane_active(lane, run)
                        if run.status == "queued":
                            run.status = "launching"
                    self._persist_queue()
                    try:
                        if run.status != "cancelled":
                            self._execute(run)
                    except Exception as exc:
                        if not run.cancelled:
                            run.status = "failed"
                            run.exit_code = -1
                            run.add_line("stderr", f"[server] worker error: {exc!r}")
                self._finalize_run(run)
            except Exception as exc:
                print(f"[runs] worker loop error: {exc!r}", file=sys.stderr, flush=True)
                time.sleep(0.5)

    def _execute(self, run):
        if run.cancelled:
            run.status = "cancelled"
            run.exit_code = -1
            return
        argv = run.argv()
        run.status = "launching"
        run.started_at = time.time()
        run.broadcast("status", {"status": run.status, "started_at": run.started_at})
        run.add_line("stdout", f"$ {' '.join(argv)}")
        try:
            from auth.manager import subprocess_env_for_profile

            env = subprocess_env_for_profile(run.profile_id)
        except Exception as exc:
            run.status = "failed"
            run.exit_code = -1
            run.add_line("stderr", f"[server] failed to build subprocess env: {exc!r}")
            return
        from baklog_fetcher_dispatch import apply_fetcher_env_mirror

        apply_fetcher_env_mirror(argv, env)
        launch_q = queue.Queue(maxsize=1)
        launch_abandoned = threading.Event()

        def _launch():
            try:
                p = _popen_fetcher(
                    argv,
                    cwd=str(data_root()),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    bufsize=1,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=env,
                )
            except BaseException as e:
                if not launch_abandoned.is_set():
                    launch_q.put(("err", e))
                return
            if launch_abandoned.is_set():
                if p.poll() is None and p.pid:
                    _terminate_pid(p.pid)
                run.add_line("stderr", "[server] late launch after timeout — terminated stray subprocess")
                return
            launch_q.put(("ok", p))

        threading.Thread(target=_launch, name=f"run-launch-{run.id}", daemon=True).start()
        try:
            tag, payload = launch_q.get(timeout=_run_cfg("LAUNCH_TIMEOUT_SEC", LAUNCH_TIMEOUT_SEC))
        except queue.Empty:
            launch_abandoned.set()
            run.status = "failed"
            run.exit_code = -1
            launch_timeout = _run_cfg("LAUNCH_TIMEOUT_SEC", LAUNCH_TIMEOUT_SEC)
            run.add_line(
                "stderr",
                f"[server] subprocess launch did not return within {launch_timeout}s (likely Windows AppX Python activation deadlock); abandoning the launcher thread. Restart the server if subsequent runs also fail to start.",
            )
            return
        if run.cancelled or run._finished.is_set():
            if tag == "ok" and payload is not None and (payload.poll() is None) and payload.pid:
                _terminate_pid(payload.pid)
            run.status = "cancelled"
            run.exit_code = -1
            run.add_line("stderr", "[server] cancelled during launch")
            return
        if tag == "err":
            exc = payload
            if isinstance(exc, FileNotFoundError):
                run.status = "failed"
                run.exit_code = -1
                run.add_line("stderr", f"[server] cannot launch: {exc}")
                return
            run.status = "failed"
            run.exit_code = -1
            run.add_line("stderr", f"[server] launch error: {exc!r}")
            return
        proc = payload
        if run.cancelled:
            if proc.poll() is None and proc.pid:
                _terminate_pid(proc.pid)
            run.status = "cancelled"
            run.exit_code = -1
            return
        run._proc = proc
        run.status = "running"
        run.broadcast("status", {"status": run.status, "started_at": run.started_at})
        if proc.pid:
            self._register_active_process(run, proc.pid)
        assert proc.stdout is not None
        line_queue = queue.Queue()

        def _reader():
            try:
                for raw in proc.stdout:
                    line_queue.put(raw.rstrip("\n"))
            finally:
                line_queue.put(None)

        threading.Thread(target=_reader, daemon=True).start()
        last_line_at = time.monotonic()
        last_stall_notice_at = 0.0
        run_started_mono = time.monotonic()
        max_run_sec = _max_run_seconds_for_key(run.key)
        max_runtime_killed = False
        reader_done = False
        while not reader_done:
            if run.cancelled:
                break
            try:
                line = line_queue.get(timeout=_run_cfg("STALL_POLL_SEC", STALL_POLL_SEC))
            except queue.Empty:
                line = "__POLL__"
            now = time.monotonic()
            if line == "__POLL__":
                if proc.poll() is not None and line_queue.empty():
                    break
                elapsed = now - run_started_mono
                if elapsed >= max_run_sec:
                    run.add_line(
                        "stderr",
                        f"[server] exceeded maximum runtime ({int(max_run_sec)}s) — force-killing PID {proc.pid}",
                    )
                    if proc.pid:
                        _terminate_pid(proc.pid)
                    try:
                        proc.wait(timeout=_run_cfg("TERMINATE_GRACE_SEC", TERMINATE_GRACE_SEC))
                    except Exception:
                        pass
                    max_runtime_killed = True
                    break
                silent = now - last_line_at
                if silent >= _run_cfg("SILENT_STALL_KILL_SEC", SILENT_STALL_KILL_SEC):
                    run.add_line("stderr", f"[server] no output for {int(silent)}s — force-killing PID {proc.pid}")
                    if proc.pid:
                        _terminate_pid(proc.pid)
                    try:
                        proc.wait(timeout=_run_cfg("TERMINATE_GRACE_SEC", TERMINATE_GRACE_SEC))
                    except Exception:
                        pass
                    break
                if silent >= _run_cfg("STALL_FIRST_NOTICE_SEC", STALL_FIRST_NOTICE_SEC) and (
                    last_stall_notice_at == 0.0
                    or now - last_stall_notice_at >= _run_cfg("STALL_REPEAT_SEC", STALL_REPEAT_SEC)
                ):
                    sec = int(silent)
                    run.add_line("stderr", f"[server] no output for {sec}s — still running (PID {proc.pid})")
                    last_stall_notice_at = now
                continue
            if line is None:
                reader_done = True
                break
            run.add_line("stdout", line)
            last_line_at = now
            last_stall_notice_at = 0.0
        if run.cancelled and proc.poll() is None and proc.pid:
            _terminate_pid(proc.pid)
        self._wait_or_kill_proc(run, proc)
        run.exit_code = proc.returncode if proc.returncode is not None else -1
        if max_runtime_killed:
            run.status = "failed"
            run.exit_code = -1
        elif run.cancelled:
            run.status = "cancelled"
            run.add_line("stderr", "[server] cancelled")
        elif proc.returncode == 0:
            run.status = "done"
        else:
            run.status = "failed"
        run._proc = None
