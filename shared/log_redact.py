"""Redact sensitive tokens from server diagnostics before HTTP responses."""

from __future__ import annotations

import re
from typing import Any

LOG_REDACT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]+", re.I), r"\1[redacted]"),
    # Cookie / Set-Cookie values run to end-of-line (they may contain spaces,
    # `;`, `=`); anchoring to EOL keeps a stray token from leaking past the
    # first whitespace.
    (re.compile(r"(Cookie:\s*)(.+)$", re.I | re.M), r"\1[redacted]"),
    (re.compile(r"(set-cookie:\s*)(.+)$", re.I | re.M), r"\1[redacted]"),
    (re.compile(r"(api[_-]?key[\"']?\s*[:=]\s*)[\"']?[\w\-]+", re.I), r"\1[redacted]"),
    (re.compile(r"([?&]ticket=)[^&\s]+", re.I), r"\1[redacted]"),
    (re.compile(r"(NPSSO[=:\s]+)[\w\-\.]+", re.I), r"\1[redacted]"),
    (re.compile(r"(Ubi_v1[=:\s]+)[\w\-\.]+", re.I), r"\1[redacted]"),
    (re.compile(r"(refresh_token[=:\s\"']+)[\w\-\.]+", re.I), r"\1[redacted]"),
    # Portable-bundle / secrets-export passphrase in any key=value form.
    (re.compile(r"(passphrase[\"']?\s*[=:]\s*)[\"']?[^\s\"'&,}]+", re.I), r"\1[redacted]"),
    # Per-store credential tokens that can surface in fetcher debug output.
    (re.compile(r"(GOG_AL[\"']?\s*[=:]\s*)[\"']?[\w\-\.]+", re.I), r"\1[redacted]"),
    (re.compile(r"(EPIC_AUTH_CODE[\"']?\s*[=:]\s*)[\"']?[\w\-\.]+", re.I), r"\1[redacted]"),
    (re.compile(r"(EA_BEARER_TOKEN[\"']?\s*[=:]\s*)[\"']?[\w\-\.]+", re.I), r"\1[redacted]"),
    (re.compile(r"(XBL_API_KEY[\"']?\s*[=:]\s*)[\"']?[\w\-\.]+", re.I), r"\1[redacted]"),
    (re.compile(r"(UBISOFT_SESSION_ID[\"']?\s*[=:]\s*)[\"']?[\w\-\.]+", re.I), r"\1[redacted]"),
    (re.compile(r"(STEAM_API_KEY[\"']?\s*[=:]\s*)[\"']?[\w\-\.]+", re.I), r"\1[redacted]"),
    (re.compile(r"(Authorization:\s*)(?!Bearer\s)([^\s,]+)", re.I), r"\1[redacted]"),
]


def redact_log_line(text: str) -> str:
    out = text
    for pattern, repl in LOG_REDACT_PATTERNS:
        out = pattern.sub(repl, out)
    return out


def redact_diagnostics_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Redact sensitive tokens from diagnostics fields before serving over HTTP."""
    tail = payload.get("refresh_log_tail")
    if isinstance(tail, str) and tail:
        payload = dict(payload)
        payload["refresh_log_tail"] = "\n".join(
            redact_log_line(line) for line in tail.splitlines()
        )
    return payload
