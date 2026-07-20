"""Bump version from 0.8.32 to 0.8.33 in all 3 files."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
old = "0.8.32"
new = "0.8.33"

for path in [root / "pyproject.toml", root / "package.json", root / "index.html"]:
    content = path.read_text(encoding="utf-8")
    count = content.count(old)
    if count == 0:
        # Try without dots escaped
        content = content.replace(str(old), str(new))
    else:
        content = content.replace(old, new)
    path.write_text(content, encoding="utf-8")
    print(f"{path.name}: {old} -> {new} ({count} replacements)")
