from __future__ import annotations
import re
from typing import Any
LOG_REDACT_PATTERNS: list[tuple[re.Pattern[str], str]] = [(re.compile('(Bearer\\s+)[A-Za-z0-9._\\-]+', re.I), '\\1[redacted]'), (re.compile('(Cookie:\\s*)(.+)$', re.I | re.M), '\\1[redacted]'), (re.compile('(set-cookie:\\s*)(.+)$', re.I | re.M), '\\1[redacted]'), (re.compile('(api[_-]?key[\\"\']?\\s*[:=]\\s*)[\\"\']?[\\w\\-]+', re.I), '\\1[redacted]'), (re.compile('([?&]ticket=)[^&\\s]+', re.I), '\\1[redacted]'), (re.compile('(NPSSO[=:\\s]+)[\\w\\-\\.]+', re.I), '\\1[redacted]'), (re.compile('(Ubi_v1[=:\\s]+)[\\w\\-\\.]+', re.I), '\\1[redacted]'), (re.compile('(refresh_token[=:\\s\\"\']+)[\\w\\-\\.]+', re.I), '\\1[redacted]'), (re.compile('(passphrase[\\"\']?\\s*[=:]\\s*)[\\"\']?[^\\s\\"\'&,}]+', re.I), '\\1[redacted]'), (re.compile('(GOG_AL[\\"\']?\\s*[=:]\\s*)[\\"\']?[\\w\\-\\.]+', re.I), '\\1[redacted]'), (re.compile('(EPIC_AUTH_CODE[\\"\']?\\s*[=:]\\s*)[\\"\']?[\\w\\-\\.]+', re.I), '\\1[redacted]'), (re.compile('(EA_BEARER_TOKEN[\\"\']?\\s*[=:]\\s*)[\\"\']?[\\w\\-\\.]+', re.I), '\\1[redacted]'), (re.compile('(XBL_API_KEY[\\"\']?\\s*[=:]\\s*)[\\"\']?[\\w\\-\\.]+', re.I), '\\1[redacted]'), (re.compile('(UBISOFT_SESSION_ID[\\"\']?\\s*[=:]\\s*)[\\"\']?[\\w\\-\\.]+', re.I), '\\1[redacted]'), (re.compile('(STEAM_API_KEY[\\"\']?\\s*[=:]\\s*)[\\"\']?[\\w\\-\\.]+', re.I), '\\1[redacted]'), (re.compile('(Authorization:\\s*)(?!Bearer\\s)([^\\s,]+)', re.I), '\\1[redacted]')]

def redact_log_line(text: str) -> str:
    out = text
    for pattern, repl in LOG_REDACT_PATTERNS:
        out = pattern.sub(repl, out)
    return out

def redact_diagnostics_payload(payload: dict[str, Any]) -> dict[str, Any]:
    tail = payload.get('refresh_log_tail')
    if isinstance(tail, str) and tail:
        payload = dict(payload)
        payload['refresh_log_tail'] = '\n'.join((redact_log_line(line) for line in tail.splitlines()))
    return payload