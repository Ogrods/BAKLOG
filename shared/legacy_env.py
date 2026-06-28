

def remediate_env_imported_archive(root):
    imported_path = root / ".env.imported"
    if not imported_path.is_file():
        return False
    try:
        imported_path.unlink()
        return True
    except OSError:
        return False


def _split_env_line(line):
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    key = stripped.split("=", 1)[0].strip()
    if key.startswith("export ") or key.startswith("export\t"):
        key = key[len("export") :].strip()
    return key or None


def _strip_credential_lines(text, cred_keys):
    kept = []
    removed = False
    for line in text.splitlines():
        key = _split_env_line(line)
        if key is not None and key in cred_keys:
            removed = True
            continue
        kept.append(line)
    new_text = "\n".join(kept)
    if new_text and (not new_text.endswith("\n")):
        new_text += "\n"
    return (new_text, removed)


def _has_meaningful_config(text):
    return any((_split_env_line(line) is not None for line in text.splitlines()))


def maybe_import_legacy_env(root):
    remediate_env_imported_archive(root)
    env_path = root / ".env"
    if not env_path.is_file():
        return (0, None)
    try:
        from auth.manager import credential_env_key_names, import_env_credentials
        from shared.profile_paths import DEFAULT_PROFILE_ID

        keys = import_env_credentials(profile_id=DEFAULT_PROFILE_ID)
        try:
            text = env_path.read_text(encoding="utf-8")
            new_text, _removed = _strip_credential_lines(text, credential_env_key_names())
            if _has_meaningful_config(new_text):
                env_path.write_text(new_text, encoding="utf-8")
            else:
                env_path.unlink()
        except OSError as exc:
            return (len(keys), f".env import ok but plaintext cleanup failed: {exc}")
        return (len(keys), None)
    except Exception as exc:
        return (0, str(exc))
