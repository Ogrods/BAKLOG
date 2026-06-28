from http import HTTPStatus


def _srv():
    import server

    return server


def handle_auth_secrets_export(handler):
    s = _srv()
    payload, err = s._read_json_body(handler, max_bytes=s._AUTH_JSON_MAX_BYTES)
    if err == "empty body":
        payload = {}
    elif err:
        s._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": err})
        return
    assert payload is not None
    try:
        from auth.bundle import BundleError, BundleTooLarge, bundle_filename, export_bundle

        passphrase = (payload.get("passphrase") or "").strip()
        include_profiles = payload.get("include_profiles", True)
        if not isinstance(include_profiles, bool):
            include_profiles = True
        blob = export_bundle(passphrase, include_profiles=include_profiles)
        s._send_bytes(handler, HTTPStatus.OK, blob, content_type="application/octet-stream", filename=bundle_filename())
    except ValueError as exc:
        s._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc), "code": "invalid_passphrase"})
    except BundleTooLarge as exc:
        s._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc), "code": "too_large"})
    except BundleError as exc:
        s._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc), "code": "bundle_error"})
    except Exception as exc:
        from auth.secrets import SecretsCorruptError

        if isinstance(exc, SecretsCorruptError):
            s._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc), "code": "secrets_corrupt"})
            return
        s._api_error(handler, HTTPStatus.INTERNAL_SERVER_ERROR, "export_failed", exc)


def handle_auth_secrets_reset(handler):
    s = _srv()
    payload, err = s._read_json_body(handler, max_bytes=s._AUTH_JSON_MAX_BYTES)
    if err:
        s._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": err})
        return
    assert payload is not None
    if not payload.get("confirm"):
        s._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "confirm: true required to reset the secrets store"})
        return
    try:
        from auth.secrets import reset_secrets_store, secrets_store_corrupt

        if not secrets_store_corrupt():
            s._send_json(
                handler,
                HTTPStatus.BAD_REQUEST,
                {"error": "secrets store is readable; reset refused", "code": "not_corrupt"},
            )
            return
        reset_secrets_store()
        s._send_json(handler, HTTPStatus.OK, {"ok": True})
    except Exception as exc:
        s._api_error(handler, HTTPStatus.INTERNAL_SERVER_ERROR, "secrets_reset_failed", exc)
