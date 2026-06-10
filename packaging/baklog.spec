# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for BAKLOG (Windows onedir). Run via packaging/build_windows.ps1.
# Entry point is server.py (HTTP server + fetcher dispatch). For the system tray
# icon in dev/dist builds, run tray_app.py separately — see scripts/build_installer.ps1.

import sys
from pathlib import Path

root = Path(SPEC).resolve().parent.parent

block_cipher = None

datas = [
    (str(root / "index.html"), "."),
    (str(root / "favicon.svg"), "."),
    (str(root / "dist"), "dist"),
    (str(root / "assets"), "assets"),
    (str(root / "vendor"), "vendor"),
    (str(root / "fetchers" / "manifest.json"), "fetchers"),
    (str(root / "pyproject.toml"), "."),
]

hiddenimports = [
    "baklog_fetcher_dispatch",
    "fetch_games",
    "fetch_gog",
    "fetch_psn",
    "fetch_epic",
    "fetch_amazon",
    "fetch_xbox",
    "fetch_battlenet",
    "fetch_ubisoft",
    "fetch_nintendo",
    "fetch_itch",
    "fetch_humble",
    "fetch_ea",
    "fetch_itad",
    "fetch_wishlist",
    "fetch_gog_wishlist",
    "fetch_epic_wishlist",
    "fetch_psn_wishlist",
    "fetch_ubisoft_wishlist",
    "fetch_xbox_wishlist",
    "fetch_nintendo_wishlist",
    "fetch_humble_wishlist",
    "fetch_fx",
    "fetch_free_claims",
    "enrich_hltb",
    "enrich_steam_reviews",
    "enrich_cross_store_images",
    "enrich_steam_tags",
    "enrich_protondb",
    "auth",
    "auth.cdp_browser",
    "auth.manager",
    "auth.secrets",
    "fetchers",
    "fetchers.registry",
    "shared.install_paths",
    "shared.built_frontend",
    "keyring.backends.Windows",
    "cryptography.hazmat.primitives.ciphers.aead",
]

a = Analysis(
    [str(root / "server.py")],
    pathex=[str(root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tests", "landing", "marketing", "node_modules"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="BAKLOG",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="BAKLOG",
)
