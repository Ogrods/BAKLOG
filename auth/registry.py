"""Provider definitions for the Connections page and auth flows."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

AuthKind = Literal["form", "browser", "oauth", "local", "manual"]


@dataclass(frozen=True)
class FormField:
    key: str
    label: str
    secret: bool = False
    placeholder: str = ""


@dataclass(frozen=True)
class ProviderSpec:
    key: str
    label: str
    kind: AuthKind
    description: str
    env_keys: tuple[str, ...]
    form_fields: tuple[FormField, ...] = ()
    login_url: str = ""
    success_url_pattern: str = ""
    expiry_days: int | None = None
    fetcher_keys: tuple[str, ...] = ()


PROVIDERS: dict[str, ProviderSpec] = {
    "steam": ProviderSpec(
        key="steam",
        label="Steam",
        kind="browser",
        description="Sign in to Steam — your API key and profile ID are saved automatically.",
        env_keys=("STEAM_API_KEY", "STEAM_ID"),
        login_url="https://steamcommunity.com/login/home/?goto=dev%2Fapikey",
        success_url_pattern=r"steamcommunity\.com/dev/apikey",
        fetcher_keys=("steam", "wishlistSteam", "steamReviews"),
    ),
    "gog": ProviderSpec(
        key="gog",
        label="GOG",
        kind="browser",
        description="GOG library and wishlist (gog-al session cookie).",
        env_keys=("GOG_AL",),
        login_url="https://www.gog.com/",
        success_url_pattern=r"gog\.com/(account|library|en)",
        expiry_days=14,
        fetcher_keys=("gog", "wishlistGog"),
    ),
    "psn": ProviderSpec(
        key="psn",
        label="PlayStation",
        kind="browser",
        description="Sign in on the PlayStation Store — the window closes automatically when done.",
        env_keys=("PSN_NPSSO",),
        login_url="https://store.playstation.com/en-us/",
        success_url_pattern=r"store\.playstation\.com",
        expiry_days=30,
        fetcher_keys=("psn",),
    ),
    "epic": ProviderSpec(
        key="epic",
        label="Epic Games (library)",
        kind="oauth",
        description="Epic launcher OAuth for owned games. Refresh token cached locally.",
        env_keys=("EPIC_AUTH_CODE",),
        login_url="https://www.epicgames.com/id/api/redirect?clientId=34a02cf8f4414e29b15921876da36f9a&responseType=code",
        success_url_pattern=r"authorizationCode",
        expiry_days=30,
        fetcher_keys=("epic",),
    ),
    "epic_wishlist": ProviderSpec(
        key="epic_wishlist",
        label="Epic (wishlist)",
        kind="browser",
        description="Epic Games Store storefront cookie for wishlist GraphQL.",
        env_keys=("EPIC_STORE_COOKIE",),
        login_url="https://store.epicgames.com/en-US/wishlist",
        success_url_pattern=r"store\.epicgames\.com",
        expiry_days=7,
        fetcher_keys=("wishlistEpic",),
    ),
    "amazon": ProviderSpec(
        key="amazon",
        label="Amazon Games",
        kind="local",
        description="Reads the Amazon Games launcher SQLite database on this PC.",
        env_keys=("AMAZON_GAMES_SQL_DIR",),
        fetcher_keys=("amazon",),
    ),
    "xbox": ProviderSpec(
        key="xbox",
        label="Xbox",
        kind="browser",
        description="Sign in to OpenXBL (xbl.io) — your API key is saved automatically.",
        env_keys=("XBL_API_KEY",),
        form_fields=(
            FormField(
                "XBL_API_KEY",
                "Or paste OpenXBL API key (from xbl.io dashboard)",
                secret=True,
            ),
        ),
        login_url="https://xbl.io/login",
        success_url_pattern=r"xbl\.io/(dashboard|app)",
        fetcher_keys=("xbox",),
    ),
    "itch": ProviderSpec(
        key="itch",
        label="itch.io",
        kind="manual",
        description=(
            "itch.io blocks automated browsers (Cloudflare). Open API keys in Chrome/Edge, "
            "copy your key, paste below, then Save."
        ),
        env_keys=("ITCH_API_KEY",),
        form_fields=(FormField("ITCH_API_KEY", "API key", secret=True),),
        login_url="https://itch.io/user/settings/api-keys",
        fetcher_keys=("itch",),
    ),
    "itad": ProviderSpec(
        key="itad",
        label="IsThereAnyDeal",
        kind="manual",
        description=(
            "ITAD blocks automated browsers. Open My Apps in Chrome/Edge, open your app, "
            "copy the API key (UUID), paste below, then Save."
        ),
        env_keys=("ITAD_API_KEY",),
        form_fields=(FormField("ITAD_API_KEY", "API key (UUID)", secret=True),),
        login_url="https://isthereanydeal.com/apps/my/",
        fetcher_keys=("itad",),
    ),
    "battlenet": ProviderSpec(
        key="battlenet",
        label="Battle.net",
        kind="browser",
        description="Battle.net account games list (session cookie).",
        env_keys=("BATTLENET_COOKIE",),
        login_url="https://account.battle.net/",
        success_url_pattern=r"account\.battle\.net/(games|overview|details)",
        expiry_days=7,
        fetcher_keys=("battlenet",),
    ),
    "nintendo": ProviderSpec(
        key="nintendo",
        label="Nintendo",
        kind="browser",
        description="Nintendo eShop purchase history (~2 years).",
        env_keys=("NINTENDO_COOKIE",),
        login_url="https://ec.nintendo.com/my/transactions/",
        success_url_pattern=r"ec\.nintendo\.com",
        expiry_days=14,
        fetcher_keys=("nintendo",),
    ),
    "ubisoft": ProviderSpec(
        key="ubisoft",
        label="Ubisoft Connect",
        kind="browser",
        description="Ubisoft Connect library (Authorization + Ubi-SessionId headers).",
        env_keys=("UBISOFT_AUTH", "UBISOFT_SESSION_ID", "UBISOFT_APP_ID"),
        login_url="https://www.ubisoft.com/en-us/ubisoft-connect",
        success_url_pattern=r"(ubisoft\.com|ubi\.com)",
        expiry_days=7,
        fetcher_keys=("ubisoft",),
    ),
}


def provider_order() -> list[str]:
    return list(PROVIDERS.keys())


def spec_for(key: str) -> ProviderSpec:
    if key not in PROVIDERS:
        raise KeyError(f"unknown provider: {key}")
    return PROVIDERS[key]
