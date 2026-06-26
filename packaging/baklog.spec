# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for BAKLOG (Windows onedir). Run via packaging/build_windows.ps1.
# Dual entry: BAKLOG.exe (server + fetcher dispatch) and BAKLOG Tray.exe (primary launcher).

import sys
from pathlib import Path

root = Path(SPEC).resolve().parent.parent
app_icon = str(root / "packaging" / "BAKLOG.ico")

block_cipher = None

datas = [
    (str(root / "index.html"), "."),
    (str(root / "favicon.svg"), "."),
    (str(root / "packaging" / "BAKLOG.ico"), "."),
    (str(root / "assets" / "tray-icon.png"), "assets"),
    (str(root / "dist"), "dist"),
    (str(root / "assets"), "assets"),
    (str(root / "vendor"), "vendor"),
    (str(root / "curated"), "curated"),
    (str(root / "fetchers" / "manifest.json"), "fetchers"),
    (str(root / "pyproject.toml"), "."),
]

_fetcher_scripts = sorted((root / "fetchers").glob("fetch_*.py"))
_enricher_scripts = sorted((root / "fetchers").parent.joinpath("enrichers").glob("enrich_*.py"))
_extra_fetchers = [
    root / "fetchers" / "fetch_free_claims.py",
    root / "fetchers" / "fetch_claim_sources.py",
    root / "fetchers" / "build_free_claims.py",
]
_client_scripts = [p for p in (root / "clients").glob("*.py") if p.name != "__init__.py"]

def _mod(path: Path) -> str:
    rel = path.relative_to(root).with_suffix("")
    return rel.as_posix().replace("/", ".")

hiddenimports = [
    "baklog_fetcher_dispatch",
    "clients",
    *[_mod(p) for p in _client_scripts],
    "fetchers",
    "fetchers.registry",
    *[_mod(p) for p in _fetcher_scripts],
    *[_mod(p) for p in _extra_fetchers if p.is_file()],
    "enrichers",
    *[_mod(p) for p in _enricher_scripts],
    "auth",
    "auth.cdp_browser",
    "auth.manager",
    "auth.secrets",
    "shared.install_paths",
    "shared.data_dir_migration",
    "shared.bundled_auth_env",
    "shared.built_frontend",
    "shared.legacy_env",
    "keyring.backends.Windows",
    "cryptography.hazmat.primitives.ciphers.aead",
    "certifi",
    "jwt",
]

tray_hiddenimports = hiddenimports + [
    "pystray",
    "PIL",
    "PIL.Image",
    "PIL.ImageDraw",
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

a_tray = Analysis(
    [str(root / "tray_app.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[],
    hiddenimports=tray_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tests", "landing", "marketing", "node_modules"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

MERGE((a, "BAKLOG", "BAKLOG"), (a_tray, "BAKLOG", "BAKLOG Tray"))

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
pyz_tray = PYZ(a_tray.pure, a_tray.zipped_data, cipher=block_cipher)

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
    icon=app_icon,
)

exe_tray = EXE(
    pyz_tray,
    a_tray.scripts,
    [],
    exclude_binaries=True,
    name="BAKLOG Tray",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=app_icon,
)

coll = COLLECT(
    exe,
    exe_tray,
    a.binaries,
    a.zipfiles,
    a.datas,
    # MERGE assigns tray-only deps (pystray, Pillow's _imaging.pyd) to a_tray;
    # COLLECT must aggregate them too or the tray exe falls back to headless.
    a_tray.binaries,
    a_tray.zipfiles,
    a_tray.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="BAKLOG",
)
