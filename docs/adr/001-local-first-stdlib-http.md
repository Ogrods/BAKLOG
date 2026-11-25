# ADR-001: Local-first stdlib HTTP + browser-tab UI

**Status:** Accepted

## Context

BAKLOG needs a desktop backlog UI without a multi-tenant backend. A heavy
desktop shell would increase attack surface and packaging complexity.

## Decision

Serve the dashboard from a Python `ThreadingHTTPServer` on `127.0.0.1` and open
it in the user's browser. Ship optional tray/autostart via PyInstaller. Do not
wrap the app in Electron.

## Consequences

Auditable localhost stack; simple frozen builds; no Chromium-in-app shell.
UI is a normal browser tab against local APIs.
