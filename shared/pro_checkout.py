"""Polar checkout URLs for BAKLOG Pro (sync with js/pro-checkout.js)."""

from __future__ import annotations

import os

PRO_CHECKOUT_MONTHLY = (
    "https://buy.polar.sh/polar_cl_1BV0qvxl87f2YEGmZo36HvXdmTf4GHthbIjh92P2yNw"
)
PRO_CHECKOUT_YEARLY = (
    "https://buy.polar.sh/polar_cl_EluZmAQP7KUeeSQfnVfEwML7NdbrW3ruDy4SB364dE3"
)


def pro_checkout_enabled() -> bool:
    """True when Polar checkout CTAs should be live (default on; BAKLOG_PRO_CHECKOUT=0 hides them)."""
    raw = os.environ.get("BAKLOG_PRO_CHECKOUT", "").strip().lower()
    if not raw:
        return True
    return raw in ("1", "true", "yes", "on")


def public_checkout_urls() -> dict[str, str]:
    if not pro_checkout_enabled():
        return {"monthly": "", "yearly": ""}
    return {"monthly": PRO_CHECKOUT_MONTHLY, "yearly": PRO_CHECKOUT_YEARLY}
