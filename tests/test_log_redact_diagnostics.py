"""Diagnostics redaction must scrub list tails and connect logs."""

from __future__ import annotations

from shared.log_redact import redact_diagnostics_payload, redact_log_line


def test_redact_log_line_oauth_and_itad() -> None:
    line = "poll url='https://login.live.com/oauth20?code=SECRET123&x=1' ITAD_API_KEY=abcd"
    out = redact_log_line(line)
    assert "SECRET123" not in out
    assert "abcd" not in out
    assert "[redacted]" in out


def test_redact_diagnostics_payload_list_tails() -> None:
    payload = {
        "refresh_log_tail": ["Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig", "ok"],
        "apply_log_tail": "NPSSO=deadbeefcookie\nnext",
        "connect_log_tails": {
            "connect-xbox.log": [
                "poll url='https://x.com/auth#code=oauth_secret_value' token=True",
            ],
        },
        "version": "0.9.00",
    }
    out = redact_diagnostics_payload(payload)
    assert isinstance(out["refresh_log_tail"], list)
    assert "eyJhbGciOiJIUzI1NiJ9" not in out["refresh_log_tail"][0]
    assert "Bearer [redacted]" in out["refresh_log_tail"][0]
    assert "deadbeefcookie" not in out["apply_log_tail"]
    assert "oauth_secret_value" not in out["connect_log_tails"]["connect-xbox.log"][0]
    assert out["version"] == "0.9.00"
