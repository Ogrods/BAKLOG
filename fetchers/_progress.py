"""Shared progress / timing helpers for fetch and enrich scripts.

Exit code contract (used across fetchers and enrichers):
  0 — success
  1 — runtime/config error
  2 — refused to write (empty library result)
  3 — refused to write (suspicious drift vs prior file)
  4 — auth failure (expired/invalid credential)
"""

from __future__ import annotations

EXIT_CODE_AUTH = 4

import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TypeVar

T = TypeVar("T")


def started(label: str) -> float:
    """Print a run header and return monotonic start time."""
    iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"=== {label} started at {iso} ===", flush=True)
    return time.monotonic()


def heartbeat(msg: str) -> None:
    """Print a single progress heartbeat line."""
    print(f"  · {msg}", flush=True)


def pct(done: int, total: int) -> str:
    """Return a percent string for progress display, or empty when total is unknown."""
    if not total or total < 0:
        return ""
    return f"{min(100, round(100 * done / total))}%"


def progress_line(done: int, total: int, phase: str, detail: str = "") -> str:
    """Format a consistent progress line: ``[i/total] (NN%) phase: detail``."""
    head = f"[{done}/{total}]" if total else f"[{done}]"
    p = pct(done, total)
    bits = [head]
    if p:
        bits.append(f"({p})")
    bits.append(phase if not detail else f"{phase}: {detail}")
    return " ".join(bits)


class HeartbeatTimer:
    """Emit a heartbeat only after `interval` seconds of wall-clock silence.

    The dev server force-kills a fetcher after 180s with no stdout (stall
    watchdog). Count-based heartbeats (every N items) are unsafe when each item
    is a slow network call — N slow lookups can exceed 180s before the count
    threshold prints anything. Call `tick(msg)` every loop iteration (ideally
    *before* each slow call); it prints at most once per `interval`, guaranteeing
    silence never approaches the watchdog as long as the loop keeps turning.
    """

    def __init__(self, interval: float = 45.0) -> None:
        self.interval = interval
        self._last = time.monotonic()
        self._started = self._last
        self._done = 0
        self._total = 0
        self._phase = ""

    def reset(self) -> None:
        """Mark 'now' as the last output (call after printing elsewhere)."""
        self._last = time.monotonic()

    def set_progress(self, done: int, total: int, phase: str) -> None:
        """Remember the current progress counters for ``tick()`` without args."""
        self._done = done
        self._total = total
        self._phase = phase

    def tick(self, msg: str) -> None:
        now = time.monotonic()
        if now - self._last >= self.interval:
            heartbeat(msg)
            self._last = now

    def tick_progress(self, done: int, total: int, phase: str, detail: str = "") -> None:
        """Emit a formatted progress heartbeat at most once per ``interval``."""
        self.set_progress(done, total, phase)
        now = time.monotonic()
        if now - self._last >= self.interval:
            heartbeat(progress_line(done, total, phase, detail))
            self._last = now

    def tick_elapsed(self, phase: str) -> None:
        """Heartbeat for phases with no countable total (browser capture, bulk API)."""
        now = time.monotonic()
        if now - self._last >= self.interval:
            elapsed = int(now - self._started)
            heartbeat(f"{phase} — still working ({elapsed}s)")
            self._last = now


def run_with_heartbeat(
    fn: Callable[[], T],
    phase: str,
    *,
    interval: float = 25.0,
) -> T:
    """Run a blocking call while emitting elapsed heartbeats (no countable total)."""
    hb = HeartbeatTimer(interval=interval)
    stop = threading.Event()

    def pulse() -> None:
        while not stop.wait(interval):
            hb.tick_elapsed(phase)

    thread = threading.Thread(target=pulse, daemon=True)
    thread.start()
    try:
        return fn()
    finally:
        stop.set()
        thread.join(timeout=1.0)


def done(
    label: str,
    t0: float,
    *,
    exit_code: int = 0,
    ok: int = 0,
    warnings: int = 0,
    errors: int = 0,
    extra: str = "",
) -> int:
    """Print a run footer and return *exit_code* for ``return done(...)``."""
    elapsed = time.monotonic() - t0
    tail = f" — {extra}" if extra else ""
    print(
        f"=== {label} done in {elapsed:.1f}s — "
        f"{ok} ok, {warnings} warnings, {errors} errors (exit {exit_code}){tail} ===",
        flush=True,
    )
    return exit_code


@dataclass
class RunStats:
    """Mutable counters for end-of-run summaries."""

    ok: int = 0
    warnings: int = 0
    errors: int = 0
    warning_messages: list[str] = field(default_factory=list)

    def warn(self, msg: str) -> None:
        self.warnings += 1
        self.warning_messages.append(msg)
        print(f"  WARNING: {msg}", flush=True)

    def error(self, msg: str) -> None:
        self.errors += 1
        print(f"  ERROR: {msg}", file=sys.stderr, flush=True)

    def finish(self, label: str, t0: float, *, exit_code: int = 0, extra: str = "") -> int:
        if self.warning_messages:
            print(
                f"\n  --- {len(self.warning_messages)} warning(s) ---",
                file=sys.stderr,
                flush=True,
            )
            for w in self.warning_messages[:50]:
                print(f"    · {w}", file=sys.stderr, flush=True)
            if len(self.warning_messages) > 50:
                print(
                    f"    · … and {len(self.warning_messages) - 50} more",
                    file=sys.stderr,
                    flush=True,
                )
        return done(
            label,
            t0,
            exit_code=exit_code,
            ok=self.ok,
            warnings=self.warnings,
            errors=self.errors,
            extra=extra,
        )
