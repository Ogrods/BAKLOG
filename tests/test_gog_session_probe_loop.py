import requests

from auth.session_probe import probe_gog_session
from clients.gog_client import GogClient


class FakeResp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, *, userdata, library, owned):
        self.userdata = userdata
        self.library = library
        self.owned = owned
        self.hits = []

    def get(self, url, **_k):
        self.hits.append(url)
        if "userData.json" in url:
            return FakeResp(self.userdata)
        if "getFilteredProducts" in url:
            return FakeResp(self.library, {"products": [], "totalPages": 1})
        if "/user/data/games" in url:
            return FakeResp(self.owned, {"owned": [1, 2, 3]})
        return FakeResp(404)


def _client(tmp_path, **statuses):
    c = GogClient("fake-gog-al-token", cache_dir=tmp_path / "gogcache")
    c.session = FakeSession(**statuses)
    c._throttle = lambda: None
    return c


def test_userdata_403_but_owned_ids_work_keeps_session_alive(tmp_path):
    client = _client(tmp_path, userdata=403, library=403, owned=200)
    assert client.validate_session() is True


def test_probe_gog_session_does_not_false_expire(tmp_path, monkeypatch):
    client = _client(tmp_path, userdata=403, library=403, owned=200)
    monkeypatch.setattr("auth.session_probe.GogClient", lambda _token: client)
    assert probe_gog_session("fake-gog-al-token") is None


def test_genuinely_dead_session_still_fails(tmp_path):
    import pytest

    from clients.gog_client import GogAuthError

    client = _client(tmp_path, userdata=403, library=403, owned=403)
    with pytest.raises(GogAuthError):
        client.validate_session()


def test_healthy_session_via_library(tmp_path):
    client = _client(tmp_path, userdata=200, library=200, owned=200)
    assert client.validate_session() is True


if __name__ == "__main__":
    import tempfile
    from pathlib import Path

    from clients.gog_client import GogAuthError

    tmp = Path(tempfile.mkdtemp())
    c = _client(tmp, userdata=403, library=403, owned=200)
    try:
        result = c.validate_session()
        print(f"validate_session -> {result} (owned-IDs work; session kept alive)")
    except GogAuthError:
        print("validate_session -> RAISED GogAuthError (FALSE-EXPIRED: owned-IDs would have worked)")
