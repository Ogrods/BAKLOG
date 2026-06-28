from shared.update_messages import APPLY_BLOCKED_MESSAGES, humanize_update_error, resolve_apply_blocked_for_check


def test_humanize_fetchers_running():
    code, message = humanize_update_error("Wait for running fetchers to finish before updating")
    assert code == "fetchers_running"
    assert "Fetcher health" in message


def test_humanize_dev_runtime():
    code, message = humanize_update_error("Updates apply only to installed BAKLOG builds")
    assert code == "dev_runtime"
    assert "desktop app" in message


def test_resolve_apply_blocked_dev_runtime():
    supported, reason, message = resolve_apply_blocked_for_check(
        update_available=True,
        zip_url="https://example.com/pkg.zip",
        sha256="abc",
        runtime_label="dev",
        frozen=False,
        in_apply_platform=True,
        running_from_temp=False,
        apply_script_present=True,
    )
    assert supported is False
    assert reason == "dev_runtime"
    assert message == APPLY_BLOCKED_MESSAGES["dev_runtime"]


def test_resolve_apply_blocked_platform_zip_missing():
    supported, reason, message = resolve_apply_blocked_for_check(
        update_available=True,
        zip_url=None,
        sha256=None,
        runtime_label="installed",
        frozen=True,
        in_apply_platform=True,
        running_from_temp=False,
        apply_script_present=True,
    )
    assert supported is False
    assert reason == "platform_zip_missing"
    assert message == APPLY_BLOCKED_MESSAGES["platform_zip_missing"]


def test_resolve_apply_supported_when_ready():
    supported, reason, message = resolve_apply_blocked_for_check(
        update_available=True,
        zip_url="https://example.com/pkg.zip",
        sha256="abc" * 21 + "a",
        runtime_label="installed",
        frozen=True,
        in_apply_platform=True,
        running_from_temp=False,
        apply_script_present=True,
    )
    assert supported is True
    assert reason is None
    assert message is None


def test_resolve_apply_blocked_no_update():
    supported, reason, message = resolve_apply_blocked_for_check(
        update_available=False,
        zip_url=None,
        sha256=None,
        runtime_label="installed",
        frozen=True,
        in_apply_platform=True,
        running_from_temp=False,
        apply_script_present=True,
    )
    assert supported is False
    assert reason is None
    assert message is None
