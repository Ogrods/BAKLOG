# ADR-008: No silent background app updates

**Status:** Accepted

## Context

In-app update can check GitHub Releases and download a zip. Auto-downloading or
auto-applying on idle/quit would surprise users on bandwidth and integrity.

## Decision

Keep check-then-click only: notify, then explicit download and explicit
install/restart. Do not silently download or apply updates in the background.

## Consequences

Users consent before large downloads and before replace/relaunch. Packaging and
release notes stay the source of truth for what ships.
