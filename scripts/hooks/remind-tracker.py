import json
import sys

def main() -> int:
    try:
        json.load(sys.stdin)
    except Exception:
        pass
    msg = 'Session ending — if you completed meaningful work, update tracker.html: mark the relevant PHASES/findings entry [DONE] or [RESOLVED] with a dated note. See docs/WORKFLOW.md. Do not create PROGRESS.md. Direct-edit-first: when ..\\baklog-internal\\tracker.html exists, edit it there and run .\\scripts\\sync-internal-repo.ps1 -Push. Only if the internal clone is missing or editing is blocked (e.g. plan mode), write .cursor/tracker-pending-<slug>.md and run /apply-tracker-pending later.'
    print(json.dumps({'followup_message': msg}))
    return 0
if __name__ == '__main__':
    sys.exit(main())