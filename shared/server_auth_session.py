"""GET /api/auth/session — JWT probe + comp-Pro upgrade on login."""

from __future__ import annotations

from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler


def _srv():
    import server

    return server


def handle_auth_session_get(handler: SimpleHTTPRequestHandler) -> None:
    from shared.comp_pro import ensure_comp_pro_on_login
    from shared.entitlement import PLAN_PRO, current_plan, note_authenticated_plan
    from shared.profile_paths import get_active_profile_id
    from shared.supabase_auth import verify_bearer_user

    s = _srv()
    authorization = handler.headers.get("Authorization")
    user = verify_bearer_user(authorization)
    if not user:
        s._send_auth_required(handler)
        return
    email = user.get("email") or ""
    user_id = user.get("id") or ""
    plan = current_plan(authorization)
    refresh_session = False
    if email:
        should_pro, upgraded = ensure_comp_pro_on_login(user_id, email)
        if should_pro and plan != PLAN_PRO:
            plan = PLAN_PRO
            note_authenticated_plan(plan)
            # Only ask the client to refresh when Supabase app_metadata was updated.
            # Comp-Pro invitees without service_role on frozen builds still get plan=pro
            # in this response; forcing refreshSession caused false sign-in failures on
            # v0.8.24 when the follow-up probe missed.
            refresh_session = upgraded
    s._send_json(
        handler,
        HTTPStatus.OK,
        {
            "ok": True,
            "email": email,
            "profile": get_active_profile_id(),
            "plan": plan,
            **({"refreshSession": True} if refresh_session else {}),
        },
    )
