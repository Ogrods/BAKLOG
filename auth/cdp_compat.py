"""Minimal Playwright-shaped helpers on top of CdpPage."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from auth.cdp_browser import CdpPage


def click_by_text(
    page: CdpPage,
    labels: tuple[str, ...],
    *,
    tags: tuple[str, ...] = ("button", "a", "input[type='submit']"),
) -> bool:
    """Click the first element whose visible text matches one of *labels*."""
    label_json = json.dumps(list(labels))
    tags_json = json.dumps(list(tags))
    return bool(
        page.evaluate(
            f"""() => {{
                const labels = {label_json}.map(s => s.toLowerCase());
                const tags = {tags_json};
                const nodes = [];
                for (const tag of tags) {{
                    try {{
                        document.querySelectorAll(tag).forEach(el => nodes.push(el));
                    }} catch (e) {{}}
                }}
                for (const el of nodes) {{
                    const text = (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().toLowerCase();
                    if (labels.some(l => text.includes(l))) {{
                        el.scrollIntoView({{block: 'center'}});
                        el.click();
                        return true;
                    }}
                }}
                return false;
            }}"""
        )
    )


def click_by_text_pattern(
    page: CdpPage,
    pattern: re.Pattern[str],
    *,
    tags: tuple[str, ...] = ("button", "a"),
) -> bool:
    """Click the first element whose text matches *pattern*."""
    pat = json.dumps(pattern.pattern)
    flags = "i" if (pattern.flags & re.IGNORECASE) else ""
    tags_json = json.dumps(list(tags))
    return bool(
        page.evaluate(
            f"""() => {{
                const re = new RegExp({pat}, '{flags}');
                const tags = {tags_json};
                const nodes = [];
                for (const tag of tags) {{
                    try {{
                        document.querySelectorAll(tag).forEach(el => nodes.push(el));
                    }} catch (e) {{}}
                }}
                for (const el of nodes) {{
                    const text = (el.innerText || el.value || '').trim();
                    if (re.test(text)) {{
                        el.scrollIntoView({{block: 'center'}});
                        el.click();
                        return true;
                    }}
                }}
                return false;
            }}"""
        )
    )
