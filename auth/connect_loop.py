from __future__ import annotations
import time
from collections.abc import Callable
from typing import Any
from auth.cdp_browser import abort_if_browser_closed
PollResult = dict[str, str] | None
HintFn = Callable[[], str | None]
CheckFn = Callable[[], PollResult]

def run_connect_poll(*, context: Any, session: Any | None, deadline: float, poll_sec: float, check: CheckFn, hint: HintFn | None=None, hint_interval: float=8.0, on_signed_in: Callable[[PollResult], None] | None=None, timeout_message: str) -> dict[str, str]:
    last_hint = 0.0
    page = None
    pages = getattr(context, 'pages', None) or []
    if pages:
        page = pages[0]
    while time.time() < deadline:
        abort_if_browser_closed(context)
        creds = check()
        if creds:
            if on_signed_in:
                on_signed_in(creds)
            return creds
        now = time.time()
        if session and hint and (now - last_hint >= hint_interval):
            last_hint = now
            msg = hint()
            if msg:
                session.emit('waiting_for_user', {'message': msg})
        if page is not None:
            page.wait_for_timeout(int(poll_sec * 1000))
        else:
            time.sleep(poll_sec)
    raise RuntimeError(timeout_message)