"""Unified credential store and browser-based sign-in for store fetchers."""

from auth.manager import (
    disconnect,
    get_credentials,
    get_status,
    mark_invalid,
    resolve_env,
    set_form_credentials,
    set_master_password,
    start_browser_auth,
    subscribe_auth_events,
)

__all__ = [
    "disconnect",
    "get_credentials",
    "get_status",
    "mark_invalid",
    "resolve_env",
    "set_form_credentials",
    "set_master_password",
    "start_browser_auth",
    "subscribe_auth_events",
]
