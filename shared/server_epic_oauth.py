"""Epic OAuth CSRF state map (legacy redirect flow only)."""

from __future__ import annotations

import threading
import time

# Epic OAuth state -> (expiry_monotonic, profile_id).
# Production Epic Connect uses Playwright + authorizationCode paste (auth/runner.py);
# this map is only populated if something calls register_epic_oauth_state.
epic_oauth_states: dict[str, tuple[float, str]] = {}
_epic_oauth_states_lock = threading.Lock()


def _prune_expired_epic_oauth_states() -> None:
    now = time.monotonic()
    expired = [k for k, (exp, _) in epic_oauth_states.items() if exp < now]
    for k in expired:
        epic_oauth_states.pop(k, None)


def register_epic_oauth_state(
    state: str,
    profile_id: str | None = None,
    *,
    ttl_sec: float = 600.0,
) -> None:
    from shared.profile_paths import get_active_profile_id

    pid = profile_id or get_active_profile_id()
    with _epic_oauth_states_lock:
        _prune_expired_epic_oauth_states()
        epic_oauth_states[state] = (time.monotonic() + ttl_sec, pid)


def consume_epic_oauth_state(state: str | None) -> str | None:
    """Return bound profile_id when state is valid; None when rejected."""
    if not state:
        return None
    with _epic_oauth_states_lock:
        entry = epic_oauth_states.pop(state, None)
    if not entry:
        return None
    expires, profile_id = entry
    if expires < time.monotonic():
        return None
    return profile_id
