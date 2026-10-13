"""Markdown-safe claim labels for GitHub text (PR bodies, digest issue, comments).

Titles and ids come from scraped upstream feeds, so they are collapsed to one
line and escaped before they reach markdown: no line breaks (which could forge
digest checkbox lines), no HTML comments (which could forge ``cmd:`` markers),
no ``@`` mentions, links, or emphasis.

Stdlib only: the private commands workflow sparse-checks out ``scripts/``.
"""

from __future__ import annotations

_MD_SPECIAL = "\\`*_[]()#|~!"
_MAX_LEN = 160


def md_text(raw: object) -> str:
    text = " ".join(str(raw or "").split())
    if len(text) > _MAX_LEN:
        text = text[: _MAX_LEN - 1].rstrip() + "…"
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = "".join(f"\\{ch}" if ch in _MD_SPECIAL else ch for ch in text)
    return text.replace("@", "&#64;")


def md_label(title: object, item_id: object) -> str:
    """``Title <sub>(id)</sub>``, or just the id when the title is missing."""
    ident = md_text(item_id)
    name = md_text(title)
    if not name or name == ident:
        return ident or "(unknown)"
    return f"{name} <sub>({ident})</sub>" if ident else name
