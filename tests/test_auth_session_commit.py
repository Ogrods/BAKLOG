"""AuthSession.commit() serializes terminal credential writes against cancel()."""

from __future__ import annotations

import threading

from auth.runner import AuthSession


def test_commit_yields_true_when_live() -> None:
    session = AuthSession("s1", "epic")
    with session.commit() as live:
        assert live is True


def test_commit_yields_false_after_cancel() -> None:
    session = AuthSession("s2", "epic")
    session.cancel()
    with session.commit() as live:
        assert live is False


def test_cancel_waits_for_in_flight_commit() -> None:
    session = AuthSession("s3", "epic")
    order: list[str] = []
    inside = threading.Event()
    release = threading.Event()

    def worker() -> None:
        with session.commit() as live:
            assert live
            inside.set()
            release.wait(timeout=5)
            order.append("write")

    t = threading.Thread(target=worker)
    t.start()
    assert inside.wait(timeout=5)

    canceller = threading.Thread(target=lambda: (session.cancel(), order.append("cancel")))
    canceller.start()
    canceller.join(timeout=0.2)
    assert canceller.is_alive(), "cancel() must block while a commit is in flight"
    assert not session.is_cancelled()

    release.set()
    t.join(timeout=5)
    canceller.join(timeout=5)
    assert order == ["write", "cancel"]
    assert session.is_cancelled()
