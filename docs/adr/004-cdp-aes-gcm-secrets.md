# ADR-004: CDP sign-in + AES-GCM secrets + OS keyring

**Status:** Accepted

## Context

Many stores lack a stable public library API. Credentials must not sit in
plaintext on disk or leave the machine.

## Decision

Connect flows use a headed CDP browser session where needed. Secrets are stored
per profile in `cache/auth/secrets.bin` (AES-256-GCM) with the master key in the
OS keyring (optional scrypt master password).

## Consequences

Sign-in looks like the user on their own IP. Portable export/import is a
separate encrypted bundle path. CDP/session access remains a documented gray
area under some store ToS (see `SECURITY.md`).
