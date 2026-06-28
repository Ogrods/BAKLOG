import os


def raw_dumps_enabled():
    return os.environ.get("BAKLOG_RAW_DUMPS", "").strip().lower() in ("1", "true", "yes", "on")


def profile_raw_dump_path(filename):
    from shared.profile_paths import profile_cache_dir

    return profile_cache_dir() / filename
