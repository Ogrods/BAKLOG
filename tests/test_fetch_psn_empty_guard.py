"""PSN empty-collect must not reuse fingerprint skip exit 0."""

from __future__ import annotations

from fetchers.fetch_psn import empty_library_is_fingerprint_skip


def test_fingerprint_skip_requires_explicit_flag() -> None:
    assert empty_library_is_fingerprint_skip(
        library_skipped=True,
        only_new=True,
        refresh=False,
        has_existing=True,
    )
    # Empty collect without fingerprint hit must go through refuse_empty_result.
    assert not empty_library_is_fingerprint_skip(
        library_skipped=False,
        only_new=True,
        refresh=False,
        has_existing=True,
    )
    assert not empty_library_is_fingerprint_skip(
        library_skipped=True,
        only_new=False,
        refresh=False,
        has_existing=True,
    )
    assert not empty_library_is_fingerprint_skip(
        library_skipped=True,
        only_new=True,
        refresh=True,
        has_existing=True,
    )
    assert not empty_library_is_fingerprint_skip(
        library_skipped=True,
        only_new=True,
        refresh=False,
        has_existing=False,
    )
