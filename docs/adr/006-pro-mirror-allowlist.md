# ADR-006: Opt-in Pro mirror allowlist only

**Status:** Accepted

## Context

Some Pro users want a read-only cloud viewer or machine-to-machine import
without turning BAKLOG into a credential cloud.

## Decision

Optional Cloud sync uploads only allowlisted artifacts
(`shared/mirror_artifacts.py`). Credentials, `cache/auth/`, and `secrets.bin`
are denied. Mirror is off by default and confirm-gated.

## Consequences

baklog.app/mirror can show catalogs after opt-in; the security story stays
local-first by default. Object size caps apply in app and storage.
