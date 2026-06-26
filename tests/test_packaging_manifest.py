"""PyInstaller hiddenimports must cover every fetchers/manifest.json script."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "fetchers" / "manifest.json"
SPEC = ROOT / "packaging" / "baklog.spec"


def _script_to_module(script: str) -> str:
    return Path(script).with_suffix("").as_posix().replace("/", ".")


def _manifest_script_modules() -> set[str]:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for entry in data.get("fetchers") or []:
        script = entry.get("script")
        if script:
            modules.add(_script_to_module(str(script)))
            assert (ROOT / script).is_file(), f"missing manifest script {script}"
    return modules


def _spec_resolved_hiddenimports() -> set[str]:
    """Mirror packaging/baklog.spec dynamic hiddenimports assembly."""
    fetcher_scripts = sorted((ROOT / "fetchers").glob("fetch_*.py"))
    enricher_scripts = sorted((ROOT / "enrichers").glob("enrich_*.py"))
    extra_fetchers = [
        ROOT / "fetchers" / "fetchers.fetch_free_claims.py",
        ROOT / "fetchers" / "fetchers.fetch_claim_sources.py",
        ROOT / "fetchers" / "fetchers.build_free_claims.py",
    ]
    client_scripts = [p for p in (ROOT / "clients").glob("*.py") if p.name != "__init__.py"]

    def mod(path: Path) -> str:
        rel = path.relative_to(ROOT).with_suffix("")
        return rel.as_posix().replace("/", ".")

    out = {
        "baklog_fetcher_dispatch",
        "clients",
        *(mod(p) for p in client_scripts),
        "fetchers",
        "fetchers.registry",
        *(mod(p) for p in fetcher_scripts),
        *(mod(p) for p in extra_fetchers if p.is_file()),
        "enrichers",
        *(mod(p) for p in enricher_scripts),
        "auth",
        "auth.cdp_browser",
        "auth.manager",
        "auth.secrets",
        "shared.install_paths",
        "shared.data_dir_migration",
        "shared.built_frontend",
        "shared.legacy_env",
        "keyring.backends.Windows",
        "cryptography.hazmat.primitives.ciphers.aead",
    }
    return out


def test_manifest_scripts_in_pyinstaller_hiddenimports() -> None:
    modules = _manifest_script_modules()
    hidden = _spec_resolved_hiddenimports()
    missing = sorted(modules - hidden)
    assert not missing, (
        "packaging/baklog.spec hiddenimports missing manifest scripts: "
        + ", ".join(missing)
    )


def test_pyinstaller_hiddenimports_include_tray_deps() -> None:
    text = SPEC.read_text(encoding="utf-8")
    for mod in ("pystray", "PIL", "PIL.Image", "PIL.ImageDraw"):
        assert mod in text, f"packaging/baklog.spec tray_hiddenimports missing {mod}"


def test_pyinstaller_hiddenimports_include_data_dir_migration() -> None:
    hidden = _spec_resolved_hiddenimports()
    assert "shared.data_dir_migration" in hidden


def test_pyinstaller_datas_include_curated_feeds() -> None:
    text = SPEC.read_text(encoding="utf-8")
    assert '("curated"), "curated")' in text.replace(" ", "") or (
        'root / "curated"' in text and '"curated"' in text
    ), "packaging/baklog.spec datas must bundle curated/ (free_claims.fallback.json offline)"


def test_inno_installer_branding_assets() -> None:
    """Inno Setup wizard/icon files must exist with expected dimensions."""
    packaging = ROOT / "packaging"
    iss = (packaging / "baklog.iss").read_text(encoding="utf-8")
    for key in (
        "SetupIconFile=installer-icon.ico",
        "WizardImageFile=installer-wizard-large.bmp",
        "WizardSmallImageFile=installer-wizard-small.bmp",
    ):
        assert key in iss, f"packaging/baklog.iss missing {key}"

    def bmp_size(path: Path) -> tuple[int, int]:
        with path.open("rb") as handle:
            handle.read(18)
            width = int.from_bytes(handle.read(4), "little", signed=True)
            height = int.from_bytes(handle.read(4), "little", signed=True)
        return abs(width), abs(height)

    large_path = packaging / "installer-wizard-large.bmp"
    small_path = packaging / "installer-wizard-small.bmp"
    ico_path = packaging / "installer-icon.ico"
    assert bmp_size(large_path) == (164, 314)
    assert bmp_size(small_path) == (55, 55)
    assert ico_path.is_file() and ico_path.stat().st_size > 0
