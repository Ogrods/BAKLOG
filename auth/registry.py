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
        description="Your Steam library and wishlist.",
        env_keys=("STEAM_API_KEY", "STEAM_ID"),
        login_url="https://steamcommunity.com/login/home/?goto=dev%2Fapikey",
        success_url_pattern=r"steamcommunity\.com/dev/apikey",
        fetcher_keys=("steam", "wishlistSteam", "steamReviews"),
    ),
    "gog": ProviderSpec(
        key="gog",
        label="GOG",
        kind="browser",
        description="Your GOG library and wishlist.",
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
        description="Your PSN library and PlayStation Store wishlist.",
        env_keys=("PSN_NPSSO",),
        login_url="https://store.playstation.com/en-us/",
        success_url_pattern=r"store\.playstation\.com",
        expiry_days=30,
        fetcher_keys=("psn", "wishlistPsn"),
    ),
    "epic": ProviderSpec(
        key="epic",
        label="Epic (library)",
        kind="manual",
        description="Your Epic Games library. Click Open in browser to sign in with Epic — you'll see a short authorizationCode on the page. Paste it below; we'll exchange it for a 30-day refresh token automatically.",
        env_keys=("EPIC_AUTH_CODE",),
        form_fields=(
            FormField(
                "EPIC_AUTH_CODE",
                "Paste authorizationCode from the Epic page",
                secret=True,
                placeholder="abc123... (the value next to \"authorizationCode\")",
            ),
        ),
        login_url=(
            "https://www.epicgames.com/id/login"
            "?lang=en&redirectUrl=https%3A%2F%2Fwww.epicgames.com%2Fid%2Fapi%2Fredirect"
            "%3FclientId%3D34a02cf8f4414e29b15921876da36f9a%26responseType%3Dcode"
        ),
        expiry_days=30,
        fetcher_keys=("epic",),
    ),
    "epic_wishlist": ProviderSpec(
        key="epic_wishlist",
        label="Epic (wishlist)",
        kind="browser",
        description="Your Epic Games Store wishlist. Separate sign-in on the storefront — Cloudflare may challenge once.",
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
        description="Your Prime Gaming library, read from the Amazon Games launcher on this PC.",
        env_keys=("AMAZON_GAMES_SQL_DIR",),
        fetcher_keys=("amazon",),
    ),
    "xbox": ProviderSpec(
        key="xbox",
        label="Xbox",
        kind="browser",
        description="Your Xbox play history (every title you've launched on Xbox network). Game Pass titles you've played are tagged \u2014 we don't pull the broader Game Pass catalog.",
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
    "xbox_wishlist": ProviderSpec(
        key="xbox_wishlist",
        label="Xbox Store wishlist",
        kind="browser",
        description="Your Xbox Store wishlist. Separate sign-in on xbox.com from the Xbox play history above \u2014 wishlists aren't exposed by OpenXBL.",
        env_keys=("XBOX_WISHLIST_PROFILE",),
        login_url="https://www.xbox.com/en-us/wishlist",
        success_url_pattern=r"xbox\.com/(en-us/)?wishlist",
        expiry_days=30,
        fetcher_keys=("wishlistXbox",),
    ),
    "itch": ProviderSpec(
        key="itch",
        label="itch.io",
        kind="manual",
        description="Your itch.io library. Paste an API key from your itch settings — automated sign-in is blocked.",
        env_keys=("ITCH_API_KEY",),
        form_fields=(FormField("ITCH_API_KEY", "API key", secret=True),),
        login_url="https://itch.io/user/settings/api-keys",
        fetcher_keys=("itch",),
    ),
    "itad": ProviderSpec(
        key="itad",
        label="IsThereAnyDeal",
        kind="manual",
        description="Cross-store deal prices for your wishlist. Paste an API key from your ITAD apps page — automated sign-in is blocked.",
        env_keys=("ITAD_API_KEY",),
        form_fields=(FormField("ITAD_API_KEY", "API key (UUID)", secret=True),),
        login_url="https://isthereanydeal.com/apps/my/",
        fetcher_keys=("itad",),
    ),
    "battlenet": ProviderSpec(
        key="battlenet",
        label="Battle.net",
        kind="browser",
        description="Your Battle.net library.",
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
        description="Your Nintendo eShop purchases (digital only, last ~2 years).",
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
        description="Your Ubisoft Connect library and Ubisoft Store wishlist.",
        env_keys=("UBISOFT_AUTH", "UBISOFT_SESSION_ID", "UBISOFT_APP_ID"),
        login_url="https://www.ubisoft.com/en-us/ubisoft-connect",
        success_url_pattern=r"(ubisoft\.com|ubi\.com)",
        expiry_days=7,
        fetcher_keys=("ubisoft", "wishlistUbisoft"),
    ),
}


def provider_order() -> list[str]:
    return list(PROVIDERS.keys())


def spec_for(key: str) -> ProviderSpec:
    if key not in PROVIDERS:
        raise KeyError(f"unknown provider: {key}")
    return PROVIDERS[key]
