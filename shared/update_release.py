"""Trusted GitHub release parsing, download allowlisting, and safe bundle extraction."""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

from shared.server_support import github_releases_latest_api_url, normalize_version_tag

_COMMUNITY_JSON = Path(__file__).resolve().parent / "community.json"
_DEFAULT_REPO_SLUG = "Ogrods/BAKLOG"

STABLE_ZIP_NAME = "BAKLOG-win64.zip"
STABLE_SHA256_NAME = "BAKLOG-win64.sha256"
STABLE_SETUP_NAME = "BAKLOG-Setup.exe"

REQUIRED_BUNDLE_FILES = ("BAKLOG.exe", "BAKLOG Tray.exe")
MAX_DOWNLOAD_BYTES = 600 * 1024 * 1024  # 600 MiB hard cap

_ALLOWED_DOWNLOAD_HOSTS = frozenset({"github.com", "objects.githubusercontent.com"})


class UpdateSecurityError(ValueError):
    """Raised when update metadata or artifacts fail security validation."""


@dataclass(frozen=True)
class ReleaseArtifacts:
    tag: str
    version: str
    html_url: str
    zip_url: str
    sha256: str
    sha256_url: str | None = None


def github_repo_slug() -> str:
    try:
        raw = json.loads(_COMMUNITY_JSON.read_text(encoding="utf-8"))
        repo = str(raw.get("github_repo", "")).strip().rstrip("/")
        if repo.startswith("https://github.com/"):
            slug = repo[len("https://github.com/") :]
            if slug:
                return slug
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return _DEFAULT_REPO_SLUG


def _releases_download_prefix() -> str:
    slug = github_repo_slug().strip("/").lower()
    return f"/{slug}/releases/download/".lower()


def is_allowed_download_url(url: str) -> bool:
    """Allowlist GitHub release asset URLs only — never user-supplied arbitrary hosts."""
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return False
    if parsed.scheme != "https":
        return False
    host = (parsed.hostname or "").lower()
    if host not in _ALLOWED_DOWNLOAD_HOSTS:
        return False
    path = parsed.path or ""
    path_lower = path.lower()
    if not path_lower.startswith(_releases_download_prefix()):
        return False
    filename = PurePosixPath(path).name
    if filename not in {STABLE_ZIP_NAME, STABLE_SHA256_NAME, STABLE_SETUP_NAME}:
        return False
    return True


def parse_sha256_sidecar(text: str) -> str:
    """Parse ``<hex>  BAKLOG-win64.zip`` sidecar format."""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = re.match(r"^([0-9a-fA-F]{64})\b", stripped)
        if match:
            return match.group(1).lower()
    raise UpdateSecurityError("sha256 sidecar format invalid")


def verify_file_sha256(path: Path, expected: str) -> None:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    actual = digest.hexdigest().lower()
    expected_norm = expected.strip().lower()
    if actual != expected_norm:
        raise UpdateSecurityError("downloaded artifact sha256 mismatch")


def _asset_map(release: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    assets = release.get("assets")
    if not isinstance(assets, list):
        return out
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name", "")).strip()
        url = str(asset.get("browser_download_url", "")).strip()
        if name and url and is_allowed_download_url(url):
            out[name] = url
    return out


def build_release_artifacts(release: dict[str, Any]) -> ReleaseArtifacts:
    tag = str(release.get("tag_name", "")).strip()
    version = normalize_version_tag(tag)
    if not version:
        raise UpdateSecurityError("release tag missing")

    assets = _asset_map(release)
    zip_url = assets.get(STABLE_ZIP_NAME)
    if not zip_url:
        slug = github_repo_slug()
        zip_url = f"https://github.com/{slug}/releases/download/{tag}/{STABLE_ZIP_NAME}"
        if not is_allowed_download_url(zip_url):
            raise UpdateSecurityError("constructed zip url rejected")

    sha256_url = assets.get(STABLE_SHA256_NAME)
    sha256 = ""
    if sha256_url:
        sha256 = _fetch_text_asset(sha256_url)
        sha256 = parse_sha256_sidecar(sha256)

    html_url = str(release.get("html_url", "") or "").strip()
    return ReleaseArtifacts(
        tag=tag,
        version=version,
        html_url=html_url,
        zip_url=zip_url,
        sha256=sha256,
        sha256_url=sha256_url,
    )


def _fetch_text_asset(url: str) -> str:
    import urllib.error
    import urllib.request

    if not is_allowed_download_url(url):
        raise UpdateSecurityError("sha256 asset url not allowlisted")
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "BAKLOG-local-update-check"},
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            raw = resp.read(512)
    except urllib.error.HTTPError as exc:
        raise UpdateSecurityError(f"sha256 fetch failed: HTTP {exc.code}") from exc
    return raw.decode("utf-8", errors="replace")


def fetch_release_artifacts() -> ReleaseArtifacts:
    from shared.server_support import fetch_latest_github_release

    release = fetch_latest_github_release()
    if not release:
        raise UpdateSecurityError("no GitHub release metadata")
    return build_release_artifacts(release)


def fetch_url_to_file(url: str, dest: Path, *, max_bytes: int = MAX_DOWNLOAD_BYTES) -> int:
    """Stream an allowlisted URL to *dest*. Returns bytes written."""
    import urllib.error
    import urllib.request

    if not is_allowed_download_url(url):
        raise UpdateSecurityError("download url not allowlisted")

    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "BAKLOG-local-update-check"},
    )
    total = 0
    try:
        with urllib.request.urlopen(req, timeout=60) as resp, dest.open("wb") as handle:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise UpdateSecurityError("download exceeds size cap")
                handle.write(chunk)
    except urllib.error.HTTPError as exc:
        if dest.is_file():
            dest.unlink(missing_ok=True)
        raise UpdateSecurityError(f"download failed: HTTP {exc.code}") from exc
    except OSError as exc:
        if dest.is_file():
            dest.unlink(missing_ok=True)
        raise UpdateSecurityError(f"download write failed: {exc}") from exc
    return total


def _zip_member_is_safe(member_name: str) -> bool:
    normalized = member_name.replace("\\", "/")
    if normalized.startswith("/") or ".." in PurePosixPath(normalized).parts:
        return False
    return True


def safe_extract_zip(zip_path: Path, dest_dir: Path) -> Path:
    """Extract *zip_path* into *dest_dir* with path-traversal guards. Returns bundle root."""
    dest_resolved = dest_dir.resolve()
    dest_resolved.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            if not _zip_member_is_safe(info.filename):
                raise UpdateSecurityError(f"unsafe zip member: {info.filename}")
            target = (dest_resolved / info.filename).resolve()
            if dest_resolved not in target.parents and target != dest_resolved:
                raise UpdateSecurityError(f"zip member escapes target dir: {info.filename}")
        archive.extractall(dest_resolved)

    return locate_bundle_root(dest_resolved)


def locate_bundle_root(extracted_dir: Path) -> Path:
    """Find the directory containing required frozen executables."""
    for exe in extracted_dir.rglob("BAKLOG.exe"):
        parent = exe.parent
        if all((parent / name).is_file() for name in REQUIRED_BUNDLE_FILES):
            return parent.resolve()
    raise UpdateSecurityError("extracted bundle missing BAKLOG executables")


def recommended_artifact(runtime_label: str) -> str:
    if runtime_label in {"installed", "portable"}:
        return "zip"
    return "none"


def release_api_url() -> str:
    return github_releases_latest_api_url()
