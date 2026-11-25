# ADR-003: Fetcher exit codes and refuse-empty/drift

**Status:** Accepted

## Context

A failed or empty store response must not silently overwrite a good local
catalog. Callers (UI chips, run manager, CI) need a shared contract.

## Decision

Every fetcher `main() -> int` uses codes from `fetchers/_progress.py`:
`0` ok, `1` error, `2` empty refused, `3` drift refused, `4` auth failure.

## Consequences

Empty/drift runs leave prior `games_*.json` intact. UI and SSE can surface
auth vs transient failure distinctly.
