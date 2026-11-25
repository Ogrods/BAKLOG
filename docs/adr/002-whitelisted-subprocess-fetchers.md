# ADR-002: Whitelisted subprocess fetchers via manifest

**Status:** Accepted

## Context

Each storefront has different auth and parsing needs. Running arbitrary scripts
from the UI would be unsafe; inlining every store into `server.py` would not scale.

## Decision

Register fetchers in `fetchers/manifest.json`. The server only spawns
manifest-whitelisted keys via `/api/run/<key>`. UI registry is generated from
`fetchers/registry.py` and drift-tested.

## Consequences

Clear extension point for new stores; fail-closed against unknown scripts;
library / wishlist / prices / enrich groups stay explicit.
