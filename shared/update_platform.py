import subprocess
import sys

_PLATFORM_ARTIFACTS = {
    "win32": ("BAKLOG-win64.zip", "BAKLOG-win64.sha256"),
    "darwin": ("BAKLOG-macos.zip", "BAKLOG-macos.sha256"),
}
_PLATFORM_BUNDLE_FILES = {"win32": ("BAKLOG.exe", "BAKLOG Tray.exe"), "darwin": ("BAKLOG", "BAKLOG Tray")}
_PLATFORM_APPLY_SCRIPT = {"win32": "apply_update.ps1", "darwin": "apply_update.sh"}
_SUPPORTED_APPLY_PLATFORMS = frozenset({"win32", "darwin"})


def release_platform(platform=None):
    plat = platform or sys.platform
    if plat in _PLATFORM_ARTIFACTS:
        return plat
    return "win32"


def current_platform():
    return sys.platform


def is_in_app_apply_platform(platform=None):
    return (platform or sys.platform) in _SUPPORTED_APPLY_PLATFORMS


def stable_zip_name(platform=None):
    plat = platform or sys.platform
    if plat not in _PLATFORM_ARTIFACTS:
        raise ValueError(f"unsupported update platform: {plat}")
    return _PLATFORM_ARTIFACTS[plat][0]


def stable_sha256_name(platform=None):
    plat = platform or sys.platform
    if plat not in _PLATFORM_ARTIFACTS:
        raise ValueError(f"unsupported update platform: {plat}")
    return _PLATFORM_ARTIFACTS[plat][1]


def allowed_asset_names():
    names = set()
    for zip_name, sha_name in _PLATFORM_ARTIFACTS.values():
        names.add(zip_name)
        names.add(sha_name)
    names.add("BAKLOG-Setup.exe")
    return frozenset(names)


def apply_script_name(platform=None):
    plat = platform or sys.platform
    if plat not in _PLATFORM_APPLY_SCRIPT:
        raise ValueError(f"unsupported update platform: {plat}")
    return _PLATFORM_APPLY_SCRIPT[plat]


def required_bundle_files(platform=None):
    plat = platform or sys.platform
    if plat not in _PLATFORM_BUNDLE_FILES:
        raise ValueError(f"unsupported update platform: {plat}")
    return _PLATFORM_BUNDLE_FILES[plat]


def server_binary_name(platform=None):
    return required_bundle_files(platform)[0]


def tray_binary_name(platform=None):
    return required_bundle_files(platform)[1]


def launch_apply_subprocess(*, script, manifest_path, install_dir):
    platform = sys.platform
    if platform == "win32":
        cmd = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-ManifestPath",
            str(manifest_path),
        ]
    elif platform == "darwin":
        cmd = ["/bin/bash", str(script), str(manifest_path)]
    else:
        raise OSError(f"In-app apply is not supported on {platform}")
    return subprocess.Popen(cmd, cwd=str(install_dir))
