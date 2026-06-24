#!/usr/bin/env python3
"""Unified local security audit: profile isolation + client storage registry.

Usage:
  .\\.venv\\Scripts\\python.exe scripts\\audit_security.py
  .\\.venv\\Scripts\\python.exe scripts\\audit_security.py --fail-on high
  .\\.venv\\Scripts\\python.exe scripts\\audit_security.py --ignore-disk-bleed
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PROFILES_DIR = ROOT / "profiles"
JS_DIR = ROOT / "js"

GLOBAL_LS_ALLOWLIST = frozenset({
    "baklog-active-profile",
    "baklog-debug",
    "baklog-debug-pro",
    "baklog-perf",
    "baklog-error-log",
    "steam-backlog-personal",
    "baklog-admin.knownAutoIds",
})

GLOBAL_SS_ALLOWLIST = frozenset({
    "baklog-stale-chunk-reload",
})

EXPECTED_SCOPED_LS_BASES = frozenset({
    "steam-backlog-ui-prefs",
    "baklog-itad-snapshot",
    "baklog-claims-snapshot",
    "steam-backlog-personal",
    "steam-backlog-manual-games",
    "steam-backlog-library-first-seen",
    "baklog-known-library-keys",
    "baklog-spotlight-recent",
    "baklog-fetcher-auth-cooldown",
    "baklog-reconnect-dismissed",
    "baklog-itad-last-auto-run",
    "baklog-claims-last-auto-run",
    "baklog-auto-stale-last-run",
    "baklog-library-watch",
    "baklog-ad-cursors",
    "baklog-color-theme",
    "baklog-fetcher-stat-layout",
    "baklog.coverGalleryMode",
    "baklog-dash-failed-covers",
    "baklog-landscape-covers",
    "baklog-metrics-rendered",
    "baklog-metrics-untapped-batch-seeded",
})

EXPECTED_SCOPED_SS_BASES = frozenset({
    "fetcher-suppressed-run-ids",
    "fetcher-last-seq-by-run",
    "__baklogMetricSeed",
    "baklog-pro-welcome",
})

PERSONAL_BLEED_KEYS = ("__dismissedClaims", "__dismissedClaimKeys", "__purgedClaimKeys")


@dataclass
class Finding:
    severity: str
    code: str
    message: str


@dataclass
class AuditReport:
    findings: list[Finding] = field(default_factory=list)

    def add(self, severity: str, code: str, message: str) -> None:
        self.findings.append(Finding(severity, code, message))


def _personal_blob(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    inner = doc.get("personal")
    return inner if isinstance(inner, dict) else doc if isinstance(doc, dict) else {}


def _personal_maps(personal: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for key in PERSONAL_BLEED_KEYS:
        val = personal.get(key)
        if isinstance(val, dict) and val:
            out[key] = val
    return out


def _shared_identical_entries(a_map: dict[str, Any], b_map: dict[str, Any], min_count: int = 3) -> list[str]:
    shared = set(a_map) & set(b_map)
    identical = [k for k in shared if a_map[k] == b_map[k]]
    return identical if len(identical) >= min_count else []


def audit_disk_personal_bleed(report: AuditReport, *, skip: bool = False) -> None:
    if skip or not PROFILES_DIR.is_dir():
        return
    profiles: dict[str, dict[str, dict[str, Any]]] = {}
    for entry in sorted(PROFILES_DIR.iterdir()):
        if not entry.is_dir():
            continue
        maps = _personal_maps(_personal_blob(entry / "data" / "personal.json"))
        if maps:
            profiles[entry.name] = maps

    ids = list(profiles.keys())
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            for field_key in PERSONAL_BLEED_KEYS:
                a_map = profiles[a].get(field_key) or {}
                b_map = profiles[b].get(field_key) or {}
                identical = _shared_identical_entries(a_map, b_map)
                if not identical:
                    continue
                code = "DISMISS_BLEED" if field_key == "__dismissedClaims" else "PERSONAL_BLEED"
                report.add(
                    "high",
                    code,
                    f"profiles/{a} and profiles/{b} share {len(identical)} "
                    f"{field_key} id(s) with identical values (likely legacy bleed). "
                    f"Sample: {identical[:3]}",
                )


def audit_profile_catalog_isolation(report: AuditReport) -> None:
    if not PROFILES_DIR.is_dir():
        return
    for entry in sorted(PROFILES_DIR.iterdir()):
        if not entry.is_dir():
            continue
        for cat in entry.glob("games_*.json"):
            if not cat.is_file():
                report.add(
                    "high",
                    "CATALOG_MISSING",
                    f"{cat.relative_to(ROOT)} is not a regular file",
                )


def _registry_source_text() -> str:
    chunks: list[str] = []
    for rel in ("state.js", "profiles.js"):
        path = JS_DIR / rel
        if path.is_file():
            chunks.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(chunks)


def audit_scoped_registry(report: AuditReport) -> None:
    text = _registry_source_text()
    if not text:
        return
    for base in EXPECTED_SCOPED_LS_BASES | EXPECTED_SCOPED_SS_BASES:
        if base not in text:
            report.add(
                "medium",
                "REGISTRY_DRIFT",
                f"Expected profile-scoped base {base!r} missing from js/profiles.js / state.js",
            )
    if "LS_ACTIVE_VIEW_SESSION" not in text:
        report.add(
            "medium",
            "REGISTRY_DRIFT",
            "LS_ACTIVE_VIEW_SESSION missing from js/profiles.js session registry",
        )


def _parse_storage_key_helpers() -> set[str]:
    profiles_js = JS_DIR / "profiles.js"
    if not profiles_js.is_file():
        return set()
    text = profiles_js.read_text(encoding="utf-8", errors="replace")
    helpers = set(re.findall(r"export function (\w+StorageKey|\w+SessionKey)", text))
    return helpers


def audit_helper_registry_coverage(report: AuditReport) -> None:
    profiles_js = JS_DIR / "profiles.js"
    if not profiles_js.is_file():
        return
    text = profiles_js.read_text(encoding="utf-8", errors="replace")
    ls_match = re.search(
        r"PROFILE_SCOPED_STORAGE_KEYS = Object\.freeze\(\[(.*?)\]\)",
        text,
        re.S,
    )
    ss_match = re.search(
        r"PROFILE_SCOPED_SESSION_KEYS = Object\.freeze\(\[(.*?)\]\)",
        text,
        re.S,
    )
    if not ls_match or not ss_match:
        report.add("high", "REGISTRY_DRIFT", "Could not parse PROFILE_SCOPED_* lists in js/profiles.js")
        return
    ls_bases = set(re.findall(r"(?:LS_\w+|PREFS_KEY|STORAGE_KEY|[A-Z_]+_PREFIX)", ls_match.group(1)))
    for helper in _parse_storage_key_helpers():
        if helper.endswith("SessionKey"):
            continue
        # helpers resolve at runtime — ensure exported names exist
        if f"export function {helper}" not in text:
            report.add("medium", "REGISTRY_DRIFT", f"Missing helper export {helper} in js/profiles.js")


def audit_js_localstorage_keys(report: AuditReport) -> None:
    pattern = re.compile(
        r"localStorage\.(?:getItem|setItem|removeItem)\(\s*['\"]([^'\"]+)['\"]",
    )
    for js_path in sorted(JS_DIR.glob("*.js")):
        text = js_path.read_text(encoding="utf-8", errors="replace")
        for match in pattern.finditer(text):
            key = match.group(1)
            if "${" in key:
                continue
            if key in GLOBAL_LS_ALLOWLIST or key in EXPECTED_SCOPED_LS_BASES:
                continue
            report.add(
                "medium",
                "LS_UNSCOPED",
                f"localStorage key {key!r} in {js_path.relative_to(ROOT)} without profile scoping",
            )


def audit_js_sessionstorage_keys(report: AuditReport) -> None:
    pattern = re.compile(
        r"sessionStorage\.(?:getItem|setItem|removeItem)\(\s*['\"]([^'\"]+)['\"]",
    )
    for js_path in sorted(JS_DIR.glob("*.js")):
        text = js_path.read_text(encoding="utf-8", errors="replace")
        for match in pattern.finditer(text):
            key = match.group(1)
            if key in GLOBAL_SS_ALLOWLIST or key in EXPECTED_SCOPED_SS_BASES:
                continue
            report.add(
                "medium",
                "SS_UNSCOPED",
                f"sessionStorage key {key!r} in {js_path.relative_to(ROOT)} without profile scoping",
            )


def _bleed_remediation_hint() -> str:
    return (
        "Remediation: reload the app (client no longer merges default localStorage into other profiles). "
        "Run scripts/clean_profile_dismiss_bleed.py --dry-run then --apply, or restore hidden claims in the UI."
    )


def run_audit(*, ignore_disk_bleed: bool = False) -> AuditReport:
    report = AuditReport()
    audit_disk_personal_bleed(report, skip=ignore_disk_bleed)
    audit_profile_catalog_isolation(report)
    audit_scoped_registry(report)
    audit_helper_registry_coverage(report)
    audit_js_localstorage_keys(report)
    audit_js_sessionstorage_keys(report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fail-on",
        choices=("high", "medium", "low"),
        help="Exit 1 when findings at or above this severity exist",
    )
    parser.add_argument(
        "--ignore-disk-bleed",
        action="store_true",
        help="Skip DISMISS_BLEED / PERSONAL_BLEED checks on profiles/ disk data (CI)",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON report on stdout")
    args = parser.parse_args(argv)
    report = run_audit(ignore_disk_bleed=args.ignore_disk_bleed)
    order = {"high": 0, "medium": 1, "low": 2}
    report.findings.sort(key=lambda f: (order[f.severity], f.code))
    if args.json:
        print(json.dumps({"findings": [asdict(f) for f in report.findings]}, indent=2))
    elif not report.findings:
        print("security audit: OK (no findings)")
    else:
        by_sev: dict[str, int] = {"high": 0, "medium": 0, "low": 0}
        for f in report.findings:
            by_sev[f.severity] = by_sev.get(f.severity, 0) + 1
            print(f"[{f.severity}] {f.code}: {f.message}")
        print(
            f"\nsecurity audit: {len(report.findings)} finding(s) "
            f"(high={by_sev.get('high', 0)}, medium={by_sev.get('medium', 0)}, low={by_sev.get('low', 0)})"
        )
        if any(f.code in ("DISMISS_BLEED", "PERSONAL_BLEED") for f in report.findings):
            print(f"\n{_bleed_remediation_hint()}")
    if args.fail_on and report.findings:
        worst = min(order[f.severity] for f in report.findings)
        if worst <= order[args.fail_on]:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
