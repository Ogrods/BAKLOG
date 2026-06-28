import hashlib
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

from shared.server_support import github_releases_latest_api_url, normalize_version_tag
from shared.update_platform import (
    allowed_asset_names,
    release_platform,
    required_bundle_files,
    server_binary_name,
    stable_sha256_name,
    stable_zip_name,
)

_COMMUNITY_JSON = Path(__file__).resolve().parent / "community.json"
_DEFAULT_REPO_SLUG = "Ogrods/BAKLOG"
STABLE_ZIP_NAME = stable_zip_name("win32")
STABLE_SHA256_NAME = stable_sha256_name("win32")
REQUIRED_BUNDLE_FILES = required_bundle_files("win32")
MAX_DOWNLOAD_BYTES = 600 * 1024 * 1024
_ALLOWED_DOWNLOAD_HOSTS = frozenset({"github.com", "objects.githubusercontent.com"})


class UpdateSecurityError(ValueError):
    pass


@dataclass(frozen=True)
class ReleaseArtifacts:
    tag: "Any"
    version: "Any"
    html_url: "Any"
    zip_url: "Any"
    sha256: "Any"
    sha256_url: "Any" = None
    release_notes: "Any" = None
    published_at: "Any" = None


def github_repo_slug():
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


def _releases_download_prefix():
    slug = github_repo_slug().strip("/").lower()
    return f"/{slug}/releases/download/".lower()


def is_allowed_download_url(url):
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
    if filename not in allowed_asset_names():
        return False
    return True


def parse_sha256_sidecar(text, *, zip_name=None):
    expected_name = zip_name or stable_zip_name(release_platform())
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = re.match("^([0-9a-fA-F]{64})\\b", stripped)
        if match:
            return match.group(1).lower()
        if expected_name in stripped:
            parts = stripped.split()
            if parts and re.fullmatch("[0-9a-fA-F]{64}", parts[0]):
                return parts[0].lower()
    raise UpdateSecurityError("sha256 sidecar format invalid")


def verify_file_sha256(path, expected):
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


def _asset_map(release):
    out = {}
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


def _sanitize_release_notes(body, *, max_len=4096):
    if not body or not str(body).strip():
        return None
    text = str(body).strip()
    if len(text) > max_len:
        return text[: max_len - 1] + "…"
    return text


def build_release_artifacts(release, platform=None):
    plat = platform or release_platform()
    zip_asset = stable_zip_name(plat)
    sha_asset = stable_sha256_name(plat)
    tag = str(release.get("tag_name", "")).strip()
    version = normalize_version_tag(tag)
    if not version:
        raise UpdateSecurityError("release tag missing")
    assets = _asset_map(release)
    zip_url = assets.get(zip_asset)
    if not zip_url and plat == "win32":
        slug = github_repo_slug()
        candidate = f"https://github.com/{slug}/releases/download/{tag}/{zip_asset}"
        if is_allowed_download_url(candidate):
            zip_url = candidate
    sha256_url = assets.get(sha_asset)
    sha256 = ""
    if sha256_url:
        sidecar = _fetch_text_asset(sha256_url)
        sha256 = parse_sha256_sidecar(sidecar, zip_name=zip_asset)
    html_url = str(release.get("html_url", "") or "").strip()
    published_at = release.get("published_at")
    published = str(published_at).strip() if published_at else None
    notes = _sanitize_release_notes(release.get("body"))
    return ReleaseArtifacts(
        tag=tag,
        version=version,
        html_url=html_url,
        zip_url=zip_url,
        sha256=sha256,
        sha256_url=sha256_url,
        release_notes=notes,
        published_at=published,
    )


def _fetch_text_asset(url):
    import urllib.error
    import urllib.request

    if not is_allowed_download_url(url):
        raise UpdateSecurityError("sha256 asset url not allowlisted")
    req = urllib.request.Request(url, headers={"User-Agent": "BAKLOG-local-update-check"})
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            raw = resp.read(512)
    except urllib.error.HTTPError as exc:
        raise UpdateSecurityError(f"sha256 fetch failed: HTTP {exc.code}") from exc
    return raw.decode("utf-8", errors="replace")


def fetch_release_artifacts(platform=None):
    from shared.server_support import fetch_latest_github_release

    release = fetch_latest_github_release()
    if not release:
        raise UpdateSecurityError("no GitHub release metadata")
    return build_release_artifacts(release, platform=platform)


def fetch_url_to_file(url, dest, *, max_bytes=MAX_DOWNLOAD_BYTES, on_progress=None):
    import urllib.error
    import urllib.request

    if not is_allowed_download_url(url):
        raise UpdateSecurityError("download url not allowlisted")
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "BAKLOG-local-update-check"})
    total = 0
    total_hint = None
    try:
        with urllib.request.urlopen(req, timeout=60) as resp, dest.open("wb") as handle:
            length = resp.headers.get("Content-Length")
            if length:
                try:
                    total_hint = int(length)
                except ValueError:
                    total_hint = None
            if on_progress:
                on_progress(0, total_hint)
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise UpdateSecurityError("download exceeds size cap")
                handle.write(chunk)
                if on_progress:
                    on_progress(total, total_hint)
    except urllib.error.HTTPError as exc:
        if dest.is_file():
            dest.unlink(missing_ok=True)
        raise UpdateSecurityError(f"download failed: HTTP {exc.code}") from exc
    except OSError as exc:
        if dest.is_file():
            dest.unlink(missing_ok=True)
        raise UpdateSecurityError(f"download write failed: {exc}") from exc
    return total


def _zip_member_is_safe(member_name):
    normalized = member_name.replace("\\", "/")
    if normalized.startswith("/") or ".." in PurePosixPath(normalized).parts:
        return False
    return True


def safe_extract_zip(zip_path, dest_dir):
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


def locate_bundle_root(extracted_dir, platform=None):
    plats = (platform,) if platform is not None else ("win32", "darwin")
    for plat in plats:
        server_name = server_binary_name(plat)
        required = required_bundle_files(plat)
        for binary in extracted_dir.rglob(server_name):
            parent = binary.parent
            if all(((parent / name).is_file() for name in required)):
                return parent.resolve()
    raise UpdateSecurityError("extracted bundle missing BAKLOG executables")


def recommended_artifact(runtime_label):
    if runtime_label in {"installed", "portable"}:
        return stable_zip_name(release_platform())
    return "none"


def release_api_url():
    return github_releases_latest_api_url()
