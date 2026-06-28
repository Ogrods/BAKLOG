import json

import scripts.audit_security as audit


def test_audit_flags_identical_dismiss_timestamps_across_profiles(tmp_path):
    profiles = tmp_path / "profiles"
    for pid, ts in (("default", 1000), ("promo", 1000)):
        dest = profiles / pid / "data"
        dest.mkdir(parents=True)
        personal = {"personal": {"__dismissedClaims": {"epic-a": ts, "epic-b": ts, "epic-c": ts}}}
        (dest / "personal.json").write_text(json.dumps(personal), encoding="utf-8")
    report = audit.AuditReport()
    old = audit.PROFILES_DIR
    audit.PROFILES_DIR = profiles
    try:
        audit.audit_disk_personal_bleed(report)
    finally:
        audit.PROFILES_DIR = old
    codes = [f.code for f in report.findings]
    assert "DISMISS_BLEED" in codes


def test_audit_ok_when_dismissals_differ(tmp_path):
    profiles = tmp_path / "profiles"
    for pid, ts in (("default", 1000), ("promo", 2000)):
        dest = profiles / pid / "data"
        dest.mkdir(parents=True)
        personal = {"personal": {"__dismissedClaims": {"epic-a": ts}}}
        (dest / "personal.json").write_text(json.dumps(personal), encoding="utf-8")
    report = audit.AuditReport()
    old = audit.PROFILES_DIR
    audit.PROFILES_DIR = profiles
    try:
        audit.audit_disk_personal_bleed(report)
    finally:
        audit.PROFILES_DIR = old
    assert not any((f.code == "DISMISS_BLEED" for f in report.findings))


def test_audit_scoped_registry_passes_on_repo_profiles_js():
    report = audit.AuditReport()
    audit.audit_scoped_registry(report)
    assert not any((f.code == "REGISTRY_DRIFT" for f in report.findings))
