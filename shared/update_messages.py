"""User-facing copy and error codes for the in-app update flow."""

from __future__ import annotations

from typing import Any

APPLY_BLOCKED_MESSAGES: dict[str, str] = {
    "dev_runtime": "Updates install only in the desktop app, not the dev server.",
    "platform_not_supported": "In-app updates are not supported on this operating system yet.",
    "temp_install": "Move BAKLOG out of your temporary extract folder before updating.",
    "missing_apply_script": (
        "This install cannot auto-update yet. Download once from the release page to enable in-app updates."
    ),
    "platform_zip_missing": (
        "No install package for your system on this release yet. Use the release page to update manually."
    ),
    "sha256_missing": "This release is missing a verification file. Use the release page to update safely.",
}

# Internal manager/API error text -> (code, user message)
_UPDATE_ERROR_ALIASES: tuple[tuple[str, str, str], ...] = (
    (
        "Updates apply only to installed BAKLOG builds",
        "dev_runtime",
        APPLY_BLOCKED_MESSAGES["dev_runtime"],
    ),
    (
        "In-app apply is not supported on this platform",
        "platform_not_supported",
        APPLY_BLOCKED_MESSAGES["platform_not_supported"],
    ),
    (
        "Move BAKLOG out of a temporary folder before updating",
        "temp_install",
        APPLY_BLOCKED_MESSAGES["temp_install"],
    ),
    (
        "Wait for running fetchers to finish before updating",
        "fetchers_running",
        "Finish or stop fetchers in Fetcher health, then try again.",
    ),
    (
        "Release download URL unavailable for this platform",
        "platform_zip_missing",
        APPLY_BLOCKED_MESSAGES["platform_zip_missing"],
    ),
    (
        "Already on latest release",
        "already_latest",
        "You are already on the latest release.",
    ),
    (
        "No verified update package is ready",
        "not_ready",
        "No verified update is ready to install. Check for updates first.",
    ),
    (
        "Release sha256 unavailable",
        "sha256_missing",
        APPLY_BLOCKED_MESSAGES["sha256_missing"],
    ),
    (
        "download cancelled",
        "download_cancelled",
        "Update download cancelled.",
    ),
    (
        "missing from install",
        "missing_apply_script",
        APPLY_BLOCKED_MESSAGES["missing_apply_script"],
    ),
    (
        "Install dir is not a BAKLOG bundle",
        "invalid_install",
        "This folder does not look like a BAKLOG install. Reinstall from the release page.",
    ),
    (
        "Failed to launch updater",
        "launch_failed",
        "Could not start the updater. Try downloading from the release page instead.",
    ),
)


def humanize_update_error(error: str) -> tuple[str | None, str]:
    """Map a server error string to (code, user-facing message)."""
    text = (error or "").strip()
    if not text:
        return None, "Update failed."
    lowered = text.lower()
    for needle, code, message in _UPDATE_ERROR_ALIASES:
        if needle.lower() in lowered:
            return code, message
    return "unknown", text


def enrich_update_api_payload(payload: dict[str, Any]) -> dict[str, Any]:
    err = payload.get("error")
    if isinstance(err, str) and err.strip():
        code, message = humanize_update_error(err)
        enriched = dict(payload)
        enriched["error_code"] = code
        enriched["error"] = message
        return enriched
    return payload


def resolve_apply_blocked_for_check(
    *,
    update_available: bool,
    zip_url: str | None,
    sha256: str | None,
    runtime_label: str,
    frozen: bool,
    in_apply_platform: bool,
    running_from_temp: bool,
    apply_script_present: bool,
) -> tuple[bool, str | None, str | None]:
    """Return (apply_supported, reason_code, user_message) for /api/update-check."""
    if not update_available:
        return False, None, None

    if runtime_label == "dev" or not frozen:
        return False, "dev_runtime", APPLY_BLOCKED_MESSAGES["dev_runtime"]

    if not in_apply_platform:
        return False, "platform_not_supported", APPLY_BLOCKED_MESSAGES["platform_not_supported"]

    if running_from_temp:
        return False, "temp_install", APPLY_BLOCKED_MESSAGES["temp_install"]

    if not apply_script_present:
        return False, "missing_apply_script", APPLY_BLOCKED_MESSAGES["missing_apply_script"]

    if not zip_url:
        return False, "platform_zip_missing", APPLY_BLOCKED_MESSAGES["platform_zip_missing"]

    if not sha256:
        return False, "sha256_missing", APPLY_BLOCKED_MESSAGES["sha256_missing"]

    return True, None, None
