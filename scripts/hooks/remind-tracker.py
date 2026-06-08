#!/usr/bin/env python3
"""Cursor stop hook: remind agent to update tracker.html after a session."""
import json
import sys


def main() -> int:
    try:
        json.load(sys.stdin)
    except Exception:
        pass

    msg = (
        "Session ending — if you completed meaningful work, update tracker.html: "
        "mark the relevant PHASES/findings entry [DONE] or [RESOLVED] with a dated note. "
        "See docs/WORKFLOW.md. Do not create PROGRESS.md. "
        "If you cannot edit tracker.html right now (e.g. plan mode or any other restriction), "
        "write the update to a temporary markdown file and apply it to tracker.html as soon as you can."
    )
    print(json.dumps({"followup_message": msg}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
