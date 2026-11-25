# ADR-005: Layered localhost authorization

**Status:** Accepted

## Context

A localhost server is reachable by any process on the machine. Origin/Referer
alone is a weak gate for mutating APIs.

## Decision

Mutating requests require `X-BAKLOG-Local: 1` (or a valid Supabase bearer when
auth is configured). Optional Supabase JWT gates `/api/*` when env is set.
`BAKLOG_ADMIN=1` unlocks `/admin/` and `/api/internal/*` for maintainers.

## Consequences

CSRF-style protection for local mutations; hosted login stays optional; admin
routes stay off by default in normal installs.
