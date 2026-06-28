import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TypeVar

T = TypeVar("T")
EXIT_CODE_AUTH = 4


def started(label):
    iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"=== {label} started at {iso} ===", flush=True)
    return time.monotonic()


def heartbeat(msg):
    print(f"  · {msg}", flush=True)


def pct(done, total):
    if not total or total < 0:
        return ""
    return f"{min(100, round(100 * done / total))}%"


def progress_line(done, total, phase, detail=""):
    head = f"[{done}/{total}]" if total else f"[{done}]"
    p = pct(done, total)
    bits = [head]
    if p:
        bits.append(f"({p})")
    bits.append(phase if not detail else f"{phase}: {detail}")
    return " ".join(bits)


class HeartbeatTimer:
    def __init__(self, interval=45.0):
        self.interval = interval
        self._last = time.monotonic()
        self._started = self._last
        self._done = 0
        self._total = 0
        self._phase = ""

    def reset(self):
        self._last = time.monotonic()

    def set_progress(self, done, total, phase):
        self._done = done
        self._total = total
        self._phase = phase

    def tick(self, msg):
        now = time.monotonic()
        if now - self._last >= self.interval:
            heartbeat(msg)
            self._last = now

    def tick_progress(self, done, total, phase, detail=""):
        self.set_progress(done, total, phase)
        now = time.monotonic()
        if now - self._last >= self.interval:
            heartbeat(progress_line(done, total, phase, detail))
            self._last = now

    def tick_elapsed(self, phase):
        now = time.monotonic()
        if now - self._last >= self.interval:
            elapsed = int(now - self._started)
            heartbeat(f"{phase} — still working ({elapsed}s)")
            self._last = now


def run_with_heartbeat(fn, phase, *, interval=25.0):
    hb = HeartbeatTimer(interval=interval)
    stop = threading.Event()

    def pulse():
        while not stop.wait(interval):
            hb.tick_elapsed(phase)

    thread = threading.Thread(target=pulse, daemon=True)
    thread.start()
    try:
        return fn()
    finally:
        stop.set()
        thread.join(timeout=1.0)


def done(label, t0, *, exit_code=0, ok=0, warnings=0, errors=0, extra=""):
    elapsed = time.monotonic() - t0
    tail = f" — {extra}" if extra else ""
    print(
        f"=== {label} done in {elapsed:.1f}s — {ok} ok, {warnings} warnings, {errors} errors (exit {exit_code}){tail} ===",
        flush=True,
    )
    return exit_code


@dataclass
class RunStats:
    ok: "Any" = 0
    warnings: "Any" = 0
    errors: "Any" = 0
    warning_messages: "Any" = field(default_factory=list)

    def warn(self, msg):
        self.warnings += 1
        self.warning_messages.append(msg)
        print(f"  WARNING: {msg}", flush=True)

    def error(self, msg):
        self.errors += 1
        print(f"  ERROR: {msg}", file=sys.stderr, flush=True)

    def finish(self, label, t0, *, exit_code=0, extra=""):
        if self.warning_messages:
            print(f"\n  --- {len(self.warning_messages)} warning(s) ---", file=sys.stderr, flush=True)
            for w in self.warning_messages[:50]:
                print(f"    · {w}", file=sys.stderr, flush=True)
            if len(self.warning_messages) > 50:
                print(f"    · … and {len(self.warning_messages) - 50} more", file=sys.stderr, flush=True)
        return done(label, t0, exit_code=exit_code, ok=self.ok, warnings=self.warnings, errors=self.errors, extra=extra)
