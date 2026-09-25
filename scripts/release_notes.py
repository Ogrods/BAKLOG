"""Release metadata checks shared by release_preflight.ps1 and release.yml.

  python scripts/release_notes.py versions            # all stamps agree with pyproject
  python scripts/release_notes.py notes 0.9.03        # print CHANGELOG [0.9.03] body
  python scripts/release_notes.py notes 0.9.03 --out notes.md
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

HTML_VERSION_STAMPS = ("index.html", "web/mirror/index.html")
_META_RE = re.compile(r'name="baklog-version"\s+content="([^"]+)"')

def read_version_stamps(root: Path = ROOT) -> dict[str, str]:
    stamps: dict[str, str] = {}
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    version = pyproject.get("project", {}).get("version")
    if not isinstance(version, str) or not version:
        raise ValueError("pyproject.toml has no [project] version")
    stamps["pyproject.toml"] = version
    pkg = json.loads((root / "package.json").read_text(encoding="utf-8"))
    stamps["package.json"] = str(pkg.get("version", ""))
    for rel in HTML_VERSION_STAMPS:
        m = _META_RE.search((root / rel).read_text(encoding="utf-8"))
        if not m:
            raise ValueError(f"{rel} has no baklog-version meta tag")
        stamps[rel] = m.group(1)
    return stamps


def changelog_section(version: str, root: Path = ROOT) -> str:
    """Body of the `## [version]` block, without the heading. Empty if absent."""
    text = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    heading = re.compile(rf"^## \[{re.escape(version)}\][^\n]*\n", re.MULTILINE)
    m = heading.search(text)
    if not m:
        return ""
    rest = text[m.end():]
    nxt = re.search(r"^## \[", rest, re.MULTILINE)
    return (rest[: nxt.start()] if nxt else rest).strip()


def section_has_content(body: str) -> bool:
    """True when the section has at least one line that is not a heading."""
    return any(line.strip() and not line.lstrip().startswith("#") for line in body.splitlines())


def _cmd_versions() -> int:
    stamps = read_version_stamps()
    if len(set(stamps.values())) != 1:
        detail = ", ".join(f"{k}={v}" for k, v in stamps.items())
        print(f"Version mismatch: {detail}", file=sys.stderr)
        return 1
    print(next(iter(stamps.values())))
    return 0


def _cmd_notes(version: str, out: str | None, root: Path = ROOT) -> int:
    body = changelog_section(version.lstrip("v"), root)
    if not section_has_content(body):
        print(f"CHANGELOG.md has no [{version.lstrip('v')}] section with notes under it", file=sys.stderr)
        return 1
    if out:
        Path(out).write_text(body + "\n", encoding="utf-8")
    else:
        print(body)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("versions")
    notes = sub.add_parser("notes")
    notes.add_argument("version")
    notes.add_argument("--out")
    args = parser.parse_args(argv)
    if args.cmd == "versions":
        return _cmd_versions()
    return _cmd_notes(args.version, args.out)


if __name__ == "__main__":
    sys.exit(main())
