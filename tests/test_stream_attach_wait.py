"""SSE attach long-wait is capped to avoid multi-minute handler holds."""

from shared.server_stream_tickets import (
    STREAM_ATTACH_LONG_WAIT_SEC,
    STREAM_ATTACH_SHORT_WAIT_SEC,
)


def test_stream_attach_long_wait_capped() -> None:
    assert STREAM_ATTACH_SHORT_WAIT_SEC == 2.0
    assert STREAM_ATTACH_LONG_WAIT_SEC == 30.0
