"""Tests for CodeQL-safe hostname allowlist helpers."""

from auth.url_hosts import cookie_domain_matches, host_matches


def test_host_matches_battlenet_subdomain() -> None:
    assert host_matches("https://account.battle.net/games", "battle.net") is True


def test_host_matches_exact_account_host() -> None:
    assert host_matches("https://account.battle.net/games", "account.battle.net") is True


def test_host_matches_rejects_suffix_spoof() -> None:
    assert host_matches("https://evilbattle.net/", "battle.net") is False
    assert host_matches("https://notbattle.net/", "battle.net") is False


def test_host_matches_epic_store() -> None:
    assert host_matches("https://store.epicgames.com/wishlist", "store.epicgames.com") is True


def test_host_matches_rejects_epic_host_spoof() -> None:
    assert (
        host_matches("https://evilstore.epicgames.com.attacker.tld/", "store.epicgames.com")
        is False
    )


def test_host_matches_psn_store() -> None:
    assert host_matches("https://store.playstation.com/en-us/", "store.playstation.com") is True
    assert (
        host_matches("https://evilstore.playstation.com.attacker.tld/", "store.playstation.com")
        is False
    )
    assert (
        host_matches("https://example.com/?q=store.playstation.com", "store.playstation.com")
        is False
    )


def test_cookie_domain_matches_battlenet() -> None:
    assert cookie_domain_matches(".battle.net", "battle.net") is True
    assert cookie_domain_matches("account.battle.net", "battle.net") is True
    assert cookie_domain_matches("notbattle.net", "battle.net") is False
