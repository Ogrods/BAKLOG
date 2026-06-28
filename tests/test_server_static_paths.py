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
    ],
)
def test_static_class(path, expected):
    assert server._static_class(path) == expected


def test_normalize_static_path_decodes_percent_encoding():
    assert server._normalize_static_path("/%2eenv") == "/.env"
    assert server._normalize_static_path("/Cache/Auth/x") == "/cache/auth/x"


def test_resolved_static_path_blocks_dotenv(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("SECRET=1", encoding="utf-8")
    monkeypatch.setattr(server, "ROOT", tmp_path)
    monkeypatch.setattr("shared.install_paths.data_root", lambda: tmp_path)
    assert server._resolved_static_path_allowed(str(env_file)) is False


def test_resolved_static_path_allows_public_asset(tmp_path, monkeypatch):
    index = tmp_path / "index.html"
    index.write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr("shared.install_paths.data_root", lambda: tmp_path)
    import shared.profile_paths as profile_paths

    monkeypatch.setattr(profile_paths, "ROOT", tmp_path)
    assert server._resolved_static_path_allowed(str(index)) is True


def test_resolved_static_path_allows_profile_catalog(tmp_path, monkeypatch):
    import shared.profile_paths as profile_paths

    monkeypatch.setattr(profile_paths, "ROOT", tmp_path)
    cat = tmp_path / "profiles" / "uid-a" / "games_steam.json"
    cat.parent.mkdir(parents=True)
    cat.write_text("{}", encoding="utf-8")
    assert server._resolved_static_path_allowed(str(cat)) is True
