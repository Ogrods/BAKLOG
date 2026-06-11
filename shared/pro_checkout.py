"""Polar checkout URLs for BAKLOG Pro (sync with js/pro-checkout.js)."""

from __future__ import annotations

PRO_CHECKOUT_MONTHLY = (
    "https://buy.polar.sh/polar_cl_1BV0qvxl87f2YEGmZo36HvXdmTf4GHthbIjh92P2yNw"
)
PRO_CHECKOUT_YEARLY = (
    "https://buy.polar.sh/polar_cl_EluZmAQP7KUeeSQfnVfEwML7NdbrW3ruDy4SB364dE3"
)


def public_checkout_urls() -> dict[str, str]:
    return {"monthly": PRO_CHECKOUT_MONTHLY, "yearly": PRO_CHECKOUT_YEARLY}
