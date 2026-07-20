"""Apply the 3 remaining fixes for the pre-beta audit."""
import sys
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# ---- Fix 1: fetch_humble_wishlist.py ----------------------------------
path1 = ROOT / "fetchers" / "fetch_humble_wishlist.py"
content = open(path1, encoding="utf-8").read()

# Add threading import
content = content.replace("import sys\n", "import sys\nimport threading\n")

# Replace multi-line with
old_with = """    with launch_persistent_profile(
        str(profile),
        headless=False,
        window_position=_WL_WINDOW_POS,
        window_size=_WL_WINDOW_SIZE,
    ) as ctx:"""

new_with = """    ctx = launch_persistent_profile(
        str(profile),
        headless=False,
        window_position=_WL_WINDOW_POS,
        window_size=_WL_WINDOW_SIZE,
    )
    try:"""

assert old_with in content, "humble: with pattern not found!"
content = content.replace(old_with, new_with)

# Add finally
old_ret = """        return items, False


def _build_row(item: WishlistItem, hltb: dict | None) -> dict:"""

new_ret = """        return items, False
    finally:
        threading.Thread(target=ctx.close, daemon=True).start()


def _build_row(item: WishlistItem, hltb: dict | None) -> dict:"""

assert old_ret in content, "humble: return not found!"
content = content.replace(old_ret, new_ret)

open(path1, "w", encoding="utf-8").write(content)
print("fetch_humble_wishlist.py: OK")

# ---- Fix 2: build_free_claims.py --------------------------------------
path2 = ROOT / "fetchers" / "build_free_claims.py"
content = open(path2, encoding="utf-8").read()

old_ua = 'STEAM_HEADERS = {"User-Agent": "Mozilla/5.0 backlog/1.0"}'
new_ua = """_STEAM_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)"""

assert old_ua in content, "build_free_claims: UA not found!"
content = content.replace(old_ua, new_ua)

# Replace usage of STEAM_HEADERS with _STEAM_UA
old_use = 'resp = requests.get(STEAM_STORESEARCH_URL, headers=dict(STEAM_HEADERS),'
new_use = 'resp = requests.get(STEAM_STORESEARCH_URL, headers={"User-Agent": _STEAM_UA},'
content = content.replace(old_use, new_use)

open(path2, "w", encoding="utf-8").write(content)
print("build_free_claims.py: OK")

# ---- Fix 3: server.py --------------------------------------------------
path3 = ROOT / "server.py"
content = open(path3, encoding="utf-8").read()

old_exemption = """    if path.startswith("/api/proxy/"):
        return True"""

new_exemption = """    # /api/proxy/* endpoints proxy public third-party APIs (Steam storesearch,
    # appreviews). They accept any search term but only proxy to read-only
    # endpoints on store.steampowered.com — no credentials forwarded, no write
    # access. Unauthenticated because the add-game modal calls them via bare
    # fetch() (no Bearer token), and the proxy does not expose the server to
    # SSRF (fixed target host, read-only search endpoints only).
    if path.startswith("/api/proxy/"):
        return True"""

assert old_exemption in content, "server.py: exemption not found!"
content = content.replace(old_exemption, new_exemption)

open(path3, "w", encoding="utf-8").write(content)
print("server.py: OK")

# ---- Verify syntax -----------------------------------------------------
import py_compile
for path, label in [(path1, "humble"), (path2, "build_free_claims"), (path3, "server")]:
    try:
        py_compile.compile(str(path), doraise=True)
        print(f"  {label}: syntax OK")
    except py_compile.PyCompileError as e:
        print(f"  {label}: SYNTAX ERROR: {e}")
        sys.exit(1)

print("\nAll 3 fixes applied and verified.")
