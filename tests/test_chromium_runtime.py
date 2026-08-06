"""Unit tests for managed Chrome for Testing download/cache."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Any

import pytest

import shared.chromium_runtime as crt


def _make_chrome_zip(plat: str, payload: bytes = b"fake-chrome") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        if plat == "win64":
            zf.writestr("chrome-win64/chrome.exe", payload)
        elif plat == "linux64":
            zf.writestr("chrome-linux64/chrome", payload)
        elif plat == "mac-arm64":
            zf.writestr(
                "chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/"
                "Google Chrome for Testing",
                payload,
            )
        elif plat == "mac-x64":
            zf.writestr(
                "chrome-mac-x64/Google Chrome for Testing.app/Contents/MacOS/"
                "Google Chrome for Testing",
                payload,
            )
        else:
            raise AssertionError(plat)
    return buf.getvalue()


def _pin_for(plat: str, url: str, sha256: str, version: str = "1.0.0") -> dict[str, Any]:
    return {
        "version": version,
        "channel": "Stable",
        "platforms": {plat: {"url": url, "sha256": sha256}},
    }


@pytest.fixture()
def data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("BAKLOG_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("BAKLOG_NO_CHROMIUM_DOWNLOAD", raising=False)
    return tmp_path / "data"


def test_platform_key_win(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(crt.sys, "platform", "win32")
    assert crt.platform_key() == "win64"


def test_is_allowed_cft_url() -> None:
    assert crt.is_allowed_cft_url(
        "https://storage.googleapis.com/chrome-for-testing-public/1/win64/chrome-win64.zip"
    )
    assert not crt.is_allowed_cft_url("https://evil.example/chrome.zip")
    assert not crt.is_allowed_cft_url("http://storage.googleapis.com/chrome-for-testing-public/x")


def test_safe_extract_rejects_zip_slip(tmp_path: Path) -> None:
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("../evil.exe", b"x")
    with pytest.raises(crt.ChromiumRuntimeError, match="unsafe"):
        crt.safe_extract_cft_zip(bad, tmp_path / "out")


def test_find_managed_requires_marker_and_exe(
    monkeypatch: pytest.MonkeyPatch, data_dir: Path
) -> None:
    plat = "win64"
    url = (
        "https://storage.googleapis.com/chrome-for-testing-public/"
        "1.0.0/win64/chrome-win64.zip"
    )
    sha = "a" * 64
    pin = _pin_for(plat, url, sha)
    monkeypatch.setattr(crt, "load_pin", lambda: pin)
    monkeypatch.setattr(crt, "platform_key", lambda: plat)
    assert crt.find_managed_chromium() is None

    dest = crt.managed_chromium_dir(version="1.0.0", plat=plat)
    exe = crt.managed_chromium_exe(version="1.0.0", plat=plat)
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"chrome")
    crt._write_marker(dest, version="1.0.0", plat=plat, sha256=sha, url=url)
    assert crt.find_managed_chromium() == exe


def test_ensure_downloads_when_missing(
    monkeypatch: pytest.MonkeyPatch, data_dir: Path
) -> None:
    plat = "win64"
    raw = _make_chrome_zip(plat)
    import hashlib

    sha = hashlib.sha256(raw).hexdigest()
    url = (
        "https://storage.googleapis.com/chrome-for-testing-public/"
        "9.9.9/win64/chrome-win64.zip"
    )
    pin = _pin_for(plat, url, sha, version="9.9.9")
    monkeypatch.setattr(crt, "load_pin", lambda: pin)
    monkeypatch.setattr(crt, "platform_key", lambda: plat)

    progress: list[tuple[int, int | None]] = []

    def fake_download(url_arg: str, dest: Path, *, on_progress=None, max_bytes=0):  # noqa: ANN001
        assert url_arg == url
        dest.write_bytes(raw)
        if on_progress:
            on_progress(len(raw), len(raw))
            progress.append((len(raw), len(raw)))
        return len(raw)

    monkeypatch.setattr(crt, "_download_to_file", fake_download)
    exe = crt.ensure_chromium(on_progress=lambda n, t: progress.append((n, t)))
    assert exe.is_file()
    assert exe.name == "chrome.exe"
    assert crt.find_managed_chromium() == exe
    assert progress


def test_ensure_sha_mismatch_cleans_up(
    monkeypatch: pytest.MonkeyPatch, data_dir: Path
) -> None:
    plat = "win64"
    raw = _make_chrome_zip(plat)
    url = (
        "https://storage.googleapis.com/chrome-for-testing-public/"
        "9.9.9/win64/chrome-win64.zip"
    )
    pin = _pin_for(plat, url, "b" * 64, version="9.9.9")
    monkeypatch.setattr(crt, "load_pin", lambda: pin)
    monkeypatch.setattr(crt, "platform_key", lambda: plat)

    def fake_download(url_arg: str, dest: Path, *, on_progress=None, max_bytes=0):  # noqa: ANN001
        dest.write_bytes(raw)
        return len(raw)

    monkeypatch.setattr(crt, "_download_to_file", fake_download)
    with pytest.raises(crt.ChromiumRuntimeError, match="integrity"):
        crt.ensure_chromium()
    final = crt.managed_chromium_dir(version="9.9.9", plat=plat)
    assert not final.exists() or not crt.managed_chromium_exe(version="9.9.9", plat=plat).is_file()


def test_no_download_env(
    monkeypatch: pytest.MonkeyPatch, data_dir: Path
) -> None:
    monkeypatch.setenv("BAKLOG_NO_CHROMIUM_DOWNLOAD", "1")
    monkeypatch.setattr(crt, "find_managed_chromium", lambda: None)
    with pytest.raises(crt.ChromiumRuntimeError, match="BAKLOG_NO_CHROMIUM_DOWNLOAD"):
        crt.ensure_chromium()


def test_clear_macos_quarantine_invoked(
    monkeypatch: pytest.MonkeyPatch, data_dir: Path, tmp_path: Path
) -> None:
    plat = "mac-arm64"
    raw = _make_chrome_zip(plat)
    import hashlib

    sha = hashlib.sha256(raw).hexdigest()
    url = (
        "https://storage.googleapis.com/chrome-for-testing-public/"
        "9.9.9/mac-arm64/chrome-mac-arm64.zip"
    )
    pin = _pin_for(plat, url, sha, version="9.9.9")
    monkeypatch.setattr(crt, "load_pin", lambda: pin)
    monkeypatch.setattr(crt, "platform_key", lambda: plat)
    monkeypatch.setattr(crt.sys, "platform", "darwin")

    calls: list[Path] = []

    def fake_clear(app: Path) -> None:
        calls.append(app)

    monkeypatch.setattr(crt, "clear_macos_quarantine", fake_clear)

    def fake_download(url_arg: str, dest: Path, *, on_progress=None, max_bytes=0):  # noqa: ANN001
        dest.write_bytes(raw)
        return len(raw)

    monkeypatch.setattr(crt, "_download_to_file", fake_download)
    exe = crt.ensure_chromium()
    assert exe.is_file()
    assert calls
    assert calls[0].name.endswith(".app")


def test_pin_file_committed() -> None:
    pin = crt.load_pin()
    assert pin["version"]
    for key in ("win64", "mac-arm64", "mac-x64", "linux64"):
        entry = pin["platforms"][key]
        assert crt.is_allowed_cft_url(entry["url"])
        assert len(entry["sha256"]) == 64


def test_cdp_find_uses_managed(
    monkeypatch: pytest.MonkeyPatch, data_dir: Path, tmp_path: Path
) -> None:
    import auth.cdp_browser as cdp

    monkeypatch.delenv("BAKLOG_CHROME_PATH", raising=False)
    monkeypatch.setattr(cdp, "_chromium_executable_candidates", lambda: [])
    monkeypatch.setattr(cdp.shutil, "which", lambda _name: None)

    managed = tmp_path / "managed" / "chrome.exe"
    managed.parent.mkdir(parents=True)
    managed.write_bytes(b"x")
    monkeypatch.setattr(
        "shared.chromium_runtime.find_managed_chromium",
        lambda: managed,
    )
    assert cdp.find_chromium_executable() == managed


def test_cdp_ensure_downloads_when_find_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import auth.cdp_browser as cdp

    monkeypatch.delenv("BAKLOG_CHROME_PATH", raising=False)
    managed = tmp_path / "dl" / "chrome.exe"
    managed.parent.mkdir(parents=True)
    managed.write_bytes(b"x")

    def boom() -> Path:
        raise RuntimeError("No Chrome or Edge browser found")

    monkeypatch.setattr(cdp, "find_chromium_executable", boom)
    monkeypatch.setattr(
        "shared.chromium_runtime.ensure_chromium",
        lambda *, on_progress=None: managed,
    )
    assert cdp.ensure_chromium_executable() == managed


def test_cdp_ensure_does_not_download_for_bad_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import auth.cdp_browser as cdp

    monkeypatch.setenv("BAKLOG_CHROME_PATH", "/no/such/browser.exe")
    called = {"n": 0}

    def fake_ensure(*, on_progress=None):  # noqa: ANN001
        called["n"] += 1
        raise AssertionError("should not download")

    monkeypatch.setattr("shared.chromium_runtime.ensure_chromium", fake_ensure)
    with pytest.raises(RuntimeError, match="BAKLOG_CHROME_PATH"):
        cdp.ensure_chromium_executable()
    assert called["n"] == 0


def test_launch_uses_ensure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import auth.cdp_browser as cdp

    calls: list[str] = []

    def fake_ensure(*, on_progress=None):  # noqa: ANN001
        calls.append("ensure")
        raise RuntimeError("stop before Popen")

    monkeypatch.setattr(cdp, "ensure_chromium_executable", fake_ensure)
    with pytest.raises(RuntimeError, match="stop before Popen"):
        cdp.launch_persistent_profile(tmp_path / "profile")
    assert calls == ["ensure"]
