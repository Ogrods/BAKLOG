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
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone


def started(label: str) -> float:
    """Print a run header and return monotonic start time."""
    iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"=== {label} started at {iso} ===", flush=True)
    return time.monotonic()


def heartbeat(msg: str) -> None:
    """Print a single progress heartbeat line."""
    print(f"  · {msg}", flush=True)


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
