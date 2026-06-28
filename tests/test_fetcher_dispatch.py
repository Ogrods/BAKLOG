import io
import json
import re
from pathlib import Path

from baklog_fetcher_dispatch import RUN_FETCHER_ARGS_ENV, RUN_FETCHER_ENV, parse_runtime_request, run_fetcher

_REPO = Path(__file__).resolve().parent.parent


def test_run_fetcher_unknown_key():
    assert run_fetcher("not-a-real-fetcher-key", []) == 2


def test_run_fetcher_steam_help_exits_zero():
    assert run_fetcher("steam", ["--help"]) == 0


def test_parse_runtime_request_from_argv():
    argv = ["BAKLOG.exe", "--run-fetcher", "steam", "--skip-hltb"]
    assert parse_runtime_request(argv, {}) == ("steam", ["--skip-hltb"])


def test_parse_runtime_request_server_mode_returns_none():
    assert parse_runtime_request(["BAKLOG.exe"], {}) is None


def test_parse_runtime_request_env_fallback_survives_argv_loss():
    env = {RUN_FETCHER_ENV: "steam", RUN_FETCHER_ARGS_ENV: json.dumps(["--skip-hltb"])}
    assert parse_runtime_request(["BAKLOG.exe"], env) == ("steam", ["--skip-hltb"])


def test_parse_runtime_request_env_fallback_no_args():
    env = {RUN_FETCHER_ENV: "epic"}
    assert parse_runtime_request(["BAKLOG.exe"], env) == ("epic", [])


def test_parse_runtime_request_argv_wins_over_env():
    env = {RUN_FETCHER_ENV: "epic", RUN_FETCHER_ARGS_ENV: json.dumps(["x"])}
    argv = ["BAKLOG.exe", "--run-fetcher", "steam"]
    assert parse_runtime_request(argv, env) == ("steam", [])


def test_every_fetcher_dispatches_via_argv_and_env():
    raw = json.loads(
        __import__("fetchers.registry", fromlist=["MANIFEST_PATH"]).MANIFEST_PATH.read_text(encoding="utf-8")
    )
    keys = [e["key"] for e in raw.get("fetchers") or [] if e.get("key")]
    assert keys, "manifest exposed no fetchers"
    for key in keys:
        argv = ["BAKLOG.exe", "--run-fetcher", key, "--flag"]
        assert parse_runtime_request(argv, {}) == (key, ["--flag"])
        env = {RUN_FETCHER_ENV: key, RUN_FETCHER_ARGS_ENV: json.dumps(["--flag"])}
        assert parse_runtime_request(["BAKLOG.exe"], env) == (key, ["--flag"])


def test_configure_stdout_is_line_buffered():
    from fetchers._base import configure_stdout

    buf = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", line_buffering=False)
    import sys

    saved = sys.stdout
    try:
        sys.stdout = buf
        configure_stdout()
        assert sys.stdout.line_buffering is True
    finally:
        sys.stdout = saved


def test_every_fetcher_reconfigures_stdout_line_buffered():
    reconfigure_call = re.compile("\\.reconfigure\\([^)]*\\)", re.DOTALL)
    offenders = []
    targets = sorted(
        {*_REPO.glob("fetchers/fetch_*.py"), *_REPO.glob("enrichers/enrich_*.py"), _REPO / "fetchers" / "_base.py"}
    )
    for path in targets:
        text = path.read_text(encoding="utf-8")
        for call in reconfigure_call.findall(text):
            if "line_buffering=True" not in call:
                offenders.append(f"{path.name}: {call.strip()}")
    assert not offenders, "stdout reconfigure without line_buffering=True:\n" + "\n".join(offenders)
