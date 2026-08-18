"""Static path classification and traversal guards (audit 2026-06-09)."""

from __future__ import annotations

from pathlib import Path

import pytest

import server


@pytest.mark.parametrize(
    "path,expected",
    [
        ("/tracker.html", "deny"),
        ("/TRACKER.HTML", "deny"),
        ("/tracker%2ehtml", "deny"),
        ("/.env", "deny"),
        ("/%2eenv", "deny"),
        ("/profiles/default/data/personal.json", "deny"),
        ("/Profiles/default/data/personal.json", "deny"),
        ("/cache/auth/secrets.bin", "deny"),
        ("/Cache/auth/secrets.bin", "deny"),
        ("/games_steam.json", "data"),
        ("/free_claims.json", "data"),
        ("/index.html", "public"),
        ("/js/app.js", "public"),
        ("/dist/js/app-LEFEOLTR.js", "public"),
    ],
)
def test_static_class(path: str, expected: str) -> None:
    assert server._static_class(path) == expected


def test_normalize_static_path_decodes_percent_encoding() -> None:
    assert server._normalize_static_path("/%2eenv") == "/.env"
    assert server._normalize_static_path("/Cache/Auth/x") == "/cache/auth/x"


def test_normalize_casefolds_hashed_dist_filename() -> None:
    # Classification casefolds; disk lookup must not, or Linux 404s hashed dist JS.
    assert server._normalize_static_path("/dist/js/app-LEFEOLTR.js") == "/dist/js/app-lefeoltr.js"


def test_static_relpath_preserve_case_keeps_esbuild_hash() -> None:
    from shared.server_static import static_relpath_preserve_case

    assert static_relpath_preserve_case("/dist/js/app-LEFEOLTR.js") == "dist/js/app-LEFEOLTR.js"
    assert static_relpath_preserve_case("/dist/js/app-LEFEOLTR.js?x=1") == "dist/js/app-LEFEOLTR.js"
    assert static_relpath_preserve_case("/dist/js/../js/app-LEFEOLTR.js") == "dist/js/app-LEFEOLTR.js"


def test_translate_path_serves_mixed_case_dist_hash(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dist_js = tmp_path / "dist" / "js"
    dist_js.mkdir(parents=True)
    hashed = dist_js / "app-LEFEOLTR.js"
    hashed.write_text("ok", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("shared.install_paths.bundle_root", lambda: tmp_path)
    monkeypatch.setattr("shared.profile_paths.ROOT", tmp_path)
    handler = server.Handler.__new__(server.Handler)
    resolved = Path(server.Handler.translate_path(handler, "/dist/js/app-LEFEOLTR.js"))
    assert resolved.resolve() == hashed.resolve()


def test_resolved_static_path_blocks_dotenv(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("SECRET=1", encoding="utf-8")
    monkeypatch.setattr(server, "ROOT", tmp_path)

    monkeypatch.setattr("shared.install_paths.data_root", lambda: tmp_path)
    assert server._resolved_static_path_allowed(str(env_file)) is False


def test_resolved_static_path_allows_public_asset(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    index = tmp_path / "index.html"
    index.write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr("shared.install_paths.data_root", lambda: tmp_path)
    import shared.profile_paths as profile_paths

    monkeypatch.setattr(profile_paths, "ROOT", tmp_path)
    assert server._resolved_static_path_allowed(str(index)) is True


def test_resolved_static_path_allows_profile_catalog(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    import shared.profile_paths as profile_paths

    monkeypatch.setattr(profile_paths, "ROOT", tmp_path)
    cat = tmp_path / "profiles" / "uid-a" / "games_steam.json"
    cat.parent.mkdir(parents=True)
    cat.write_text("{}", encoding="utf-8")
    assert server._resolved_static_path_allowed(str(cat)) is True
