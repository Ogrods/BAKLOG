import json
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


def click_by_text(page, labels, *, tags=("button", "a", "input[type='submit']")):
    label_json = json.dumps(list(labels))
    tags_json = json.dumps(list(tags))
    return bool(
        page.evaluate(
            f"() => {{\n                const labels = {label_json}.map(s => s.toLowerCase());\n                const tags = {tags_json};\n                const nodes = [];\n                for (const tag of tags) {{\n                    try {{\n                        document.querySelectorAll(tag).forEach(el => nodes.push(el));\n                    }} catch (e) {{}}\n                }}\n                for (const el of nodes) {{\n                    const text = (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().toLowerCase();\n                    if (labels.some(l => text.includes(l))) {{\n                        el.scrollIntoView({{block: 'center'}});\n                        el.click();\n                        return true;\n                    }}\n                }}\n                return false;\n            }}"
        )
    )


def click_by_text_pattern(page, pattern, *, tags=("button", "a")):
    pat = json.dumps(pattern.pattern)
    flags = "i" if pattern.flags & re.IGNORECASE else ""
    tags_json = json.dumps(list(tags))
    return bool(
        page.evaluate(
            f"() => {{\n                const re = new RegExp({pat}, '{flags}');\n                const tags = {tags_json};\n                const nodes = [];\n                for (const tag of tags) {{\n                    try {{\n                        document.querySelectorAll(tag).forEach(el => nodes.push(el));\n                    }} catch (e) {{}}\n                }}\n                for (const el of nodes) {{\n                    const text = (el.innerText || el.value || '').trim();\n                    if (re.test(text)) {{\n                        el.scrollIntoView({{block: 'center'}});\n                        el.click();\n                        return true;\n                    }}\n                }}\n                return false;\n            }}"
        )
    )
