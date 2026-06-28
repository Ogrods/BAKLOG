from http import HTTPStatus


def _srv():
    import server

    return server


def handle_auth_sign_out_post(handler):
    from shared.entitlement import clear_background_auth_caches

    s = _srv()
    if handler._reject_if_csrf_strict():
        return
    clear_background_auth_caches()
    s._send_json(handler, HTTPStatus.OK, {"ok": True})
