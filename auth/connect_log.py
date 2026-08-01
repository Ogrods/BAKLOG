"""Rate-limited stderr + on-disk tee for headed Connect flows.

Frozen Tray builds hide the server console, so Connect diagnostics must land
under the data dir (``connect-<provider>.log``) the same way Battle.net already
did before this helper was generalized.
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

_LOG_INTERVAL_SEC = 4.0
_last_log_by_key: dict[str, float] = {}
_log_paths: dict[str, Path | None] = {}

_PROVIDER_SAFE = re.compile(r"[^a-z0-9_-]+")


def connect_log(provider: str, message: str, *, key: str | None = None) -> None:
    """Rate-limited stderr + on-disk tee for frozen Tray builds."""
    now = time.time()
    prov = (provider or "unknown").strip().lower() or "unknown"
    dedupe_key = f"{prov}:{key or message}"
    last = _last_log_by_key.get(dedupe_key, 0.0)
    if now - last < _LOG_INTERVAL_SEC:
        return
    _last_log_by_key[dedupe_key] = now
    if len(_last_log_by_key) > 128:
        cutoff = now - (_LOG_INTERVAL_SEC * 4)
        stale = [k for k, t in _last_log_by_key.items() if t < cutoff]
        for k in stale:
            _last_log_by_key.pop(k, None)
    line = f"[{prov}] {message}"
    print(line, file=sys.stderr, flush=True)
    try:
        path = _log_paths.get(prov)
        if path is None and prov not in _log_paths:
            from shared.install_paths import data_root

            safe = _PROVIDER_SAFE.sub("-", prov).strip("-") or "unknown"
            path = data_root() / f"connect-{safe}.log"
            _log_paths[prov] = path
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(
                    f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {line}\n"
                )
    except Exception:  # noqa: BLE001
        pass


def reset_connect_log_for_tests() -> None:
    """Clear cached paths / dedupe state (unit tests only)."""
    _last_log_by_key.clear()
    _log_paths.clear()
