"""Provider definitions for the Connections page and auth flows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from auth.epic_wishlist_session import epic_store_login_url
from clients.amazon_web_client import amazon_signin_url

AuthKind = Literal["form", "browser", "oauth", "local", "manual"]
PostConnectProbe = Literal["required", "advisory", "skip"]


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
    # Short, additive "good to know" bullets shown on the Connections card.
    # Keep each line scannable; deep step-by-step instructions live elsewhere.
    tips: tuple[str, ...] = ()
    # OS restriction for this provider. Empty = all platforms (the common case).
    # Amazon Games reads a Windows-only launcher DB, so it sets ("win32",).
    platforms: tuple[str, ...] = ()
    connect_strategy: str = ""
    preserve_profile_on_reconnect: bool = False
    post_connect_probe: PostConnectProbe = "required"
    login_success_url: str = ""


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
        tips=(
            "We grab your Steam Web API key automatically once you sign in — nothing to copy.",
            "Your profile + game details must be set to Public for the library and wishlist to load.",
            "First sync of a big library can take a few minutes (Steam rate-limits); later runs use cache.",
        ),
    ),
    "gog": ProviderSpec(
        key="gog",
        label="GOG (web)",
        kind="browser",
        description="Your GOG library and wishlist via gog.com session cookie.",
        env_keys=("GOG_AL",),
        login_url="https://www.gog.com/",
        success_url_pattern=r"gog\.com/(account|library|en)",
        expiry_days=14,
        fetcher_keys=("gog", "wishlistGog"),
        tips=(
            "One sign-in covers both your GOG library and wishlist.",
            "Sessions last about two weeks — reconnect here if GOG games stop updating.",
            "On Windows/macOS with GOG Galaxy installed, the local Galaxy source below "
            "is preferred — no browser sign-in needed.",
        ),
        connect_strategy="cookie_probe",
    ),
    "gog_galaxy": ProviderSpec(
        key="gog_galaxy",
        label="GOG Galaxy (local)",
        kind="local",
        description="Your GOG library from the GOG Galaxy app on this PC (no cookie sign-in).",
        env_keys=("GOG_GALAXY_DB",),
        fetcher_keys=("gog",),
        platforms=("win32", "darwin"),
        tips=(
            "No sign-in window — we read Galaxy's local galaxy-2.0.db on this PC.",
            "Install GOG Galaxy, sign in, and sync your library once.",
            "Nothing leaves your machine for this source; it's a local file read only.",
            "Windows and macOS only — Linux has no supported Galaxy DB path.",
        ),
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
        tips=(
            "Use the Sign In button at the top-right of the store page, then keep the window "
            "open until it closes on its own.",
            "Easiest sign-in: if you have a passkey, choose \u201cSign in with a passkey\u201d "
            "and approve it on your phone \u2014 no password or 2FA codes to type.",
            "One sign-in covers your PSN library and PlayStation Store wishlist; sessions last ~30 days.",
        ),
    ),
    "epic": ProviderSpec(
        key="epic",
        label="Epic (library)",
        kind="browser",
        description=(
            "Your Epic Games library. Click Connect to sign in to Epic in a managed "
            "window — we capture and exchange the authorizationCode for a 30-day "
            "refresh token automatically. If auto-capture is ever blocked, you can "
            "still paste the code Epic shows on the page below."
        ),
        env_keys=("EPIC_AUTH_CODE",),
        form_fields=(
            FormField(
                "EPIC_AUTH_CODE",
                "Paste authorizationCode from the Epic page (fallback)",
                secret=True,
                placeholder="abc123... (the value next to \"authorizationCode\")",
            ),
        ),
        login_url=(
            "https://www.epicgames.com/id/login"
            "?lang=en&redirectUrl=https%3A%2F%2Fwww.epicgames.com%2Fid%2Fapi%2Fredirect"
            "%3FclientId%3D34a02cf8f4414e29b15921876da36f9a%26responseType%3Dcode"
        ),
        success_url_pattern=r"id/api/redirect",
        expiry_days=30,
        fetcher_keys=("epic",),
        tips=(
            "Click Connect and sign in — we grab the authorizationCode for you, no copy/paste.",
            (
                "Auto-capture blocked? Paste the authorizationCode shown on Epic's page "
                "into the fallback field."
            ),
            "We trade the code for a ~30-day refresh token, so you only do this about monthly.",
        ),
    ),
    "epic_wishlist": ProviderSpec(
        key="epic_wishlist",
        label="Epic (wishlist)",
        kind="browser",
        description=(
            "Your Epic Games Store wishlist. Separate sign-in on the storefront — "
            "Cloudflare may challenge once."
        ),
        env_keys=("EPIC_STORE_COOKIE",),
        login_url=epic_store_login_url(),
        success_url_pattern=r"store\.epicgames\.com",
        expiry_days=7,
        fetcher_keys=("wishlistEpic",),
        tips=(
            "Separate from the Epic library sign-in above \u2014 the storefront uses its own session.",
            "Cloudflare may show a quick checkbox; clear it, then let the wishlist fully load before closing.",
            "Storefront sessions are short (~7 days), so expect to reconnect this one more often.",
        ),
        connect_strategy="graphql_response",
        preserve_profile_on_reconnect=True,
        post_connect_probe="required",
        login_success_url="https://store.epicgames.com/wishlist",
    ),
    "amazon": ProviderSpec(
        key="amazon",
        label="Amazon Games (launcher)",
        kind="local",
        description=(
            "Your Prime Gaming library from the Amazon Games launcher on this PC "
            "(richest data: art, last played)."
        ),
        env_keys=("AMAZON_GAMES_SQL_DIR",),
        fetcher_keys=("amazon",),
        platforms=("win32",),
        tips=(
            "No sign-in window \u2014 we read the Amazon Games launcher's local database on this PC.",
            "Just install the Amazon Games launcher and sign in there once; keep it installed.",
            "Nothing leaves your machine for this source; it's a local file read only.",
            "Windows only \u2014 the launcher database uses Windows DPAPI. On macOS/Linux use "
            "“Amazon (Prime Gaming, web)” below.",
        ),
    ),
    "amazon_web": ProviderSpec(
        key="amazon_web",
        label="Amazon (Prime Gaming, web)",
        kind="browser",
        description=(
            "Prime Gaming claims delivered to Amazon Games (no external redemption keys). "
            "Works on any OS; complements the Windows launcher source above."
        ),
        env_keys=("AMAZON_WEB_PROFILE",),
        login_url=amazon_signin_url(),
        success_url_pattern=r"luna\.amazon\.com|gaming\.amazon\.com|amazon\.com",
        expiry_days=30,
        fetcher_keys=("amazon",),
        tips=(
            "Sign in on the Amazon page — BAKLOG sends you to My Collection after login.",
            "Imports Amazon-fulfilled Prime games only \u2014 external key drops (Epic, Steam, etc.) are skipped.",
            "Use this on macOS/Linux, or on Windows when you don't use the Amazon Games launcher.",
            "Sessions last about 30 days; reconnect if the Amazon fetcher reports auth failure.",
        ),
    ),
    "xbox": ProviderSpec(
        key="xbox",
        label="Xbox",
        kind="browser",
        description=(
            "Your Xbox play history (every title you've launched on Xbox network)."
        ),
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
        tips=(
            "Sign in at xbl.io with your Microsoft account \u2014 we save the OpenXBL API key for you.",
            "Stuck on the Microsoft login? Click \u201cSign in another way\u201d and have it email you a "
            "one-time code \u2014 no password or authenticator needed.",
            "Already have a key? Paste it in the field below instead of signing in.",
            "Pulls titles you've actually launched on Xbox network.",
        ),
    ),
    "xbox_wishlist": ProviderSpec(
        key="xbox_wishlist",
        label="Xbox Store wishlist",
        kind="browser",
        description=(
            "Your Xbox Store wishlist. Separate sign-in on xbox.com from the Xbox play "
            "history above \u2014 wishlists aren't exposed by OpenXBL."
        ),
        env_keys=("XBOX_WISHLIST_PROFILE", "XBOX_WISHLIST_TOKEN", "XBOX_WISHLIST_MARKET"),
        login_url="https://www.xbox.com/en-us/wishlist",
        success_url_pattern=r"xbox\.com/(en-us/)?wishlist",
        expiry_days=30,
        fetcher_keys=("wishlistXbox",),
        tips=(
            "Separate xbox.com sign-in from Xbox play history above \u2014 wishlists aren't in OpenXBL.",
            "Sign in with your Microsoft account and keep the window open until it closes.",
            "Easiest login: click \u201cSign in another way\u201d and have Microsoft email you a one-time "
            "code \u2014 no password or authenticator needed.",
        ),
        connect_strategy="xhr_sniffer",
        post_connect_probe="advisory",
        login_success_url="https://www.xbox.com/en-us/wishlist",
    ),
    "itch": ProviderSpec(
        key="itch",
        label="itch.io (API key)",
        kind="manual",
        description=(
            "Your itch.io library via API key. Paste a key from your itch settings — "
            "automated sign-in is blocked."
        ),
        env_keys=("ITCH_API_KEY",),
        form_fields=(FormField("ITCH_API_KEY", "API key", secret=True),),
        login_url="https://itch.io/user/settings/api-keys",
        fetcher_keys=("itch",),
        tips=(
            "Open in browser goes straight to your itch API keys page \u2014 generate one and paste it below.",
            "itch blocks automated sign-in, so the API key is the supported web path.",
            "With the itch desktop app installed, the local source below is preferred.",
            "Bundle items you haven't claimed yet won't show up until you claim them on itch.io.",
        ),
    ),
    "itch_local": ProviderSpec(
        key="itch_local",
        label="itch app (local)",
        kind="local",
        description="Your itch.io library from the itch desktop app's local database on this PC.",
        env_keys=("ITCH_BUTLER_DB",),
        fetcher_keys=("itch",),
        tips=(
            "No API key needed — we read the itch app's butler.db on this PC.",
            "Install the itch desktop app, sign in, and open your library once.",
            "Adds last-played / playtime when games are installed through the app.",
        ),
    ),
    "itad": ProviderSpec(
        key="itad",
        label="IsThereAnyDeal",
        kind="manual",
        description=(
            "Cross-store deal prices for your wishlist. Paste an API key from your ITAD "
            "apps page — automated sign-in is blocked."
        ),
        env_keys=("ITAD_API_KEY",),
        form_fields=(FormField("ITAD_API_KEY", "API key (UUID)", secret=True),),
        login_url="https://isthereanydeal.com/apps/my/",
        fetcher_keys=("itad",),
        tips=(
            "Not a store login \u2014 this powers cross-store deal prices and historical lows on your wishlist.",
            "Create an app at isthereanydeal.com/apps/my/, then paste the API key (a UUID) below.",
            "Deals refresh on their own up to once an hour while the dashboard is open.",
        ),
    ),
    "battlenet": ProviderSpec(
        key="battlenet",
        label="Battle.net",
        kind="browser",
        description="Your Battle.net library.",
        env_keys=("BATTLENET_COOKIE",),
        login_url="https://account.battle.net/games",
        success_url_pattern=r"account\.battle\.net/(games|overview|details)",
        expiry_days=7,
        fetcher_keys=("battlenet",),
        tips=(
            "Sign in at account.battle.net and open your Games list so the session is fully active.",
            "Battle.net sessions are short (~7 days) \u2014 reconnect here when the library looks stale.",
            "Covers Blizzard titles tied to your account (WoW, Diablo, Overwatch, etc.).",
        ),
        connect_strategy="cookie_api_probe",
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
        tips=(
            "Sign in with your Nintendo Account and let the eShop transactions page finish loading.",
            "Purchase history is read from your saved browser profile (not cookie text alone).",
            "Only digital eShop purchases from roughly the last two years are available \u2014 no physical carts.",
            "Sessions last about two weeks; reconnect when new eShop buys don't appear.",
        ),
    ),
    "nintendo_wishlist": ProviderSpec(
        key="nintendo_wishlist",
        label="Nintendo Store wishlist",
        kind="browser",
        description=(
            "Your Nintendo.com wish list. Separate sign-in on nintendo.com from the "
            "eShop transactions path above."
        ),
        env_keys=("NINTENDO_WISHLIST_PROFILE",),
        login_url="https://www.nintendo.com/us/wish-list/",
        success_url_pattern=r"nintendo\.com/(us/)?wish-list",
        expiry_days=30,
        fetcher_keys=("wishlistNintendo",),
        tips=(
            "Separate nintendo.com sign-in from the eShop library path above \u2014 wishlists live on the storefront.",
            "Sign in with your Nintendo Account and keep the window open until your wish list loads.",
            "If email verification is required, complete it in the browser window before closing.",
        ),
    ),
    "humble": ProviderSpec(
        key="humble",
        label="Humble Bundle",
        kind="browser",
        description="Your Humble library (purchases and keys) and Humble Store wishlist.",
        env_keys=("HUMBLE_PROFILE",),
        login_url="https://www.humblebundle.com/home/library",
        success_url_pattern=r"humblebundle\.com/(home|store)",
        expiry_days=30,
        fetcher_keys=("humble", "wishlistHumble"),
        tips=(
            "One sign-in covers both your Humble library and the Humble Store wishlist.",
            "Sign in at humblebundle.com (email or Google). Complete any CAPTCHA in the browser window.",
            "After sign-in we'll open your library page to capture the session.",
            (
                "Most Humble purchases are Steam keys \u2014 they appear as Humble-owned "
                "titles and dedupe against Steam by name."
            ),
        ),
        connect_strategy="profile_marker",
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
        tips=(
            "One sign-in covers both your Ubisoft Connect library and the Ubisoft Store wishlist.",
            "After signing in, browse to your games once so we can capture the session.",
            "If 2FA/verify leaves a blank tab, close it and click Connect again \u2014 "
            "the sign-in still completes in the main window.",
            "Sessions are short (~7 days) \u2014 reconnect here when Ubisoft data goes stale.",
        ),
    ),
    "ea": ProviderSpec(
        key="ea",
        label="EA App",
        kind="browser",
        description="Your EA App (PC) library — owned titles and EA Play vault games.",
        env_keys=("EA_PROFILE", "EA_BEARER_TOKEN"),
        login_url="https://www.ea.com/login",
        success_url_pattern=r"ea\.com",
        expiry_days=30,
        fetcher_keys=("ea",),
        tips=(
            "Sign in with your EA account in the browser window.",
            "After sign-in we'll open EA's deals page to confirm your session and save your web token.",
            "Each sync uses your saved session token; the browser profile is refreshed when needed.",
            "Only PC titles sold on EA are listed \u2014 Steam/Epic copies stay on those store fetchers.",
        ),
        connect_strategy="bearer_header",
        login_success_url="https://www.ea.com/",
    ),
}


def provider_order() -> list[str]:
    return list(PROVIDERS.keys())


def spec_for(key: str) -> ProviderSpec:
    if key not in PROVIDERS:
        raise KeyError(f"unknown provider: {key}")
    return PROVIDERS[key]
