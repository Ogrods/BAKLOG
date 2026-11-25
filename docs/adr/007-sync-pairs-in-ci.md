# ADR-007: Cross-language sync pairs enforced in CI

**Status:** Accepted

## Context

Brand colors, claim sanitizers, wishlist keys, and sponsor locations must stay
aligned across JS, Python, CSS, and landing HTML. Convention alone drifts.

## Decision

Document pairs in `AGENTS.md` hard rule 6. Fail CI when they diverge via
Vitest/pytest parity tests (e.g. `tests/sync-pairs.test.js`,
`tests/test_fetcher_registry_drift.py`, mirror/wishlist/claims parity modules).

## Consequences

Duplication is allowed when tested. Agents and humans update both sides (and
tests) in the same change.
