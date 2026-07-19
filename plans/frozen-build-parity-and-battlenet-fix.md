# Frozen Build Parity & Battle.net Window-Close Fix

> **Primary symptom**: Battle.net Connect window pops open and immediately closes on frozen builds. GOG and Humble use the same [`run_connect_poll`](auth/connect_loop.py:37) but work fine — this confirms the exception is specific to Battle.net's `check()` callback, not the poll loop itself.

## Problem Summary

1. **Battle.net Connect window pops open and immediately closes** on the frozen build (PyInstaller onedir). Works fine on dev.
2. **This is a recurring pattern**: things work on dev but break on the frozen build, and there's no systematic way to catch these before shipping.
3. The fix from [`plans/battlenet-connect-window-closes-immediately.md`](plans/battlenet-connect-window-closes-immediately.md) is already applied at [`auth/connect_extractors.py:204-209`](auth/connect_extractors.py:204), so this is a different root cause.

---

## Root Cause Analysis

The exception propagation chain for ALL browser-based connect flows (including Battle.net) is:

```
extract_battlenet_session(context)          # any exception here...
  └─ run_connect_poll                       # NOT caught here
      └─ _extract_battlenet_inline          # NOT caught here
          └─ run_browser_auth               # only catches ConnectBrowserClosed
              └─ with launch_persistent_profile(...) as context:
                  # __exit__ calls context.close() → KILLS BROWSER WINDOW
              └─ returns to _worker() in manager.py:722
                  └─ except Exception → catches error AFTER browser is dead
```

The critical gap is in [`auth/connect_loop.py:37`](auth/connect_loop.py:37): `run_connect_poll` calls `check()` (which is `extract_battlenet_session(context)`) without any try/except. **Any unexpected exception from the check function kills the browser immediately**.

### Why Frozen-Only?

The exception is most likely one that only manifests in the PyInstaller frozen environment:

| Candidate                     | Mechanism                                                                                                                                                  | Why Frozen-Only?                                                                                |
| ----------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| **Lazy import failure**       | `connect_extractors.py:197` does `from clients.battlenet_client import ...` which triggers `battlenet_client.py` top-level `import browser_cookie3 as bc3` | PyInstaller may bundle `browser_cookie3` but its native dependencies fail to resolve at runtime |
| **CDP websocket timing**      | `context.cookies()` → `_first_page_session()` → `_send()` fails with `ConnectionError("CDP connection closed")`                                            | Frozen builds may have different subprocess/thread timing causing race                          |
| **Profile path issues**       | `profile_dir("battlenet")` resolves to `%LOCALAPPDATA%\BAKLOG-Data\profiles\<id>\cache\auth\profiles\battlenet`                                            | Path permissions, creation failures, or path-too-long on migrated profiles                      |
| **Thread/signal differences** | PyInstaller's bootloader may handle daemon threads or signals differently                                                                                  | Dev uses CPython directly; frozen uses PyInstaller's bootloader                                 |

The `browser_cookie3` import is the most likely suspect because:

- It's imported at the top level of `battlenet_client.py` (line 17)
- It's a lazy import triggered on the first call to `extract_battlenet_session`
- Native C extensions inside `browser_cookie3` may not resolve in PyInstaller's bundled environment
- The `frozen_import_smoke.py` tests for it, but a successful `import` doesn't guarantee all its runtime operations work

BUT: This import is only reached when `_battlenet_has_session()` returns True. On a fresh profile with NO prior cookies, it returns False immediately and the import is never triggered. So if the user has a fresh frozen install, the crash must come from elsewhere.

The next most likely is a CDP websocket error during `context.cookies()` on the first poll cycle.

---

## Plan

### Phase 1: Add Diagnostic Logging (No Behavioral Change)

Make the frozen build capture what's actually failing, so we stop guessing.

#### 1A. Add stderr logging to `run_connect_poll`

**File**: [`auth/connect_loop.py`](auth/connect_loop.py)

Wrap the `check()` call in try/except that logs the exception to stderr before re-raising:

```python
while time.time() < deadline:
    abort_if_browser_closed(context)
    try:
        creds = check()
    except Exception:
        import sys
        import traceback
        print("[connect_loop] check() raised:", file=sys.stderr, flush=True)
        traceback.print_exc(file=sys.stderr)
        raise
    if creds:
        ...
```

This preserves existing behavior (the browser still closes) but captures the stack trace so the frozen build user can report it, or we can see it in the server console.

#### 1B. Add stderr logging to `extract_battlenet_session`

**File**: [`auth/connect_extractors.py:196-210`](auth/connect_extractors.py:196)

Add diagnostic prints around the lazy import and cookie check:

```python
def extract_battlenet_session(context: Any) -> dict[str, str] | None:
    import sys
    try:
        from clients.battlenet_client import BattleNetAuthError, probe_session
    except Exception as exc:
        print(f"[battlenet] import failed: {exc}", file=sys.stderr, flush=True)
        return None  # <-- Don't crash, just report not-ready

    if not _battlenet_has_session(context):
        return None
    header = _cookie_header(context.cookies(), (".battle.net", "battle.net"))
    if not header:
        return None
    try:
        probe_session(header)
    except BattleNetAuthError:
        return None
    return {"BATTLENET_COOKIE": header}
```

The key change: move the `import` to a try/except that **returns None** instead of propagating. This means if `browser_cookie3` fails to import on the frozen build, the poll loop keeps running instead of killing the browser.

#### 1C. Add frozen-environment diagnostics endpoint (Admin-only)

**File**: [`shared/server_internal_routes.py`](shared/server_internal_routes.py) (or new admin route)

Add `GET /api/internal/frozen-diag` (admin-gated) that returns:

- `sys.frozen` status
- `sys.executable`
- `sys.path`
- `data_root()` and `bundle_root()` resolved paths
- Key import health (`browser_cookie3`, `websocket`, etc.)
- Profile directory listing for battle.net

This gives us immediate visibility into frozen-vs-dev differences without needing SSH/remote access.

---

### Phase 2: Defensive Fix for Battle.net Window

The root fix: prevent ANY exception in the `check()` callback from killing the browser.

#### 2A. Make `run_connect_poll` resilient to check exceptions

**File**: [`auth/connect_loop.py`](auth/connect_loop.py)

Change the exception handling to treat a check failure as "not ready yet" rather than fatal:

```python
def run_connect_poll(
    *,
    context: Any,
    session: Any | None,
    deadline: float,
    poll_sec: float,
    check: CheckFn,
    hint: HintFn | None = None,
    hint_interval: float = 8.0,
    on_signed_in: Callable[[PollResult], None] | None = None,
    timeout_message: str,
) -> dict[str, str]:
    last_hint = 0.0
    page = None
    pages = getattr(context, "pages", None) or []
    if pages:
        page = pages[0]

    while time.time() < deadline:
        abort_if_browser_closed(context)
        try:
            creds = check()
        except ConnectBrowserClosed:
            raise
        except Exception:
            import sys
            import traceback
            print("[connect_loop] check() raised, retrying:", file=sys.stderr, flush=True)
            traceback.print_exc(file=sys.stderr)
            creds = None
        if creds:
            if on_signed_in:
                on_signed_in(creds)
            return creds

        now = time.time()
        if session and hint and now - last_hint >= hint_interval:
            last_hint = now
            try:
                msg = hint()
            except Exception:
                msg = None
            if msg:
                session.emit("waiting_for_user", {"message": msg})

        if page is not None:
            page.wait_for_timeout(int(poll_sec * 1000))
        else:
            time.sleep(poll_sec)

    raise RuntimeError(timeout_message)
```

Key: `ConnectBrowserClosed` is re-raised (the browser truly closed). Everything else is logged and treated as "not signed in yet."

#### 2B. Move `browser_cookie3` import to be defensive

**File**: [`auth/connect_extractors.py`](auth/connect_extractors.py)

Move the lazy import into a try/except at the function level (as shown in 1B). This is the most targeted fix if `browser_cookie3` is the culprit.

#### 2C. Add `BATTLENET_COOKIE` env fallback logging

**File**: [`auth/manager.py`](auth/manager.py) around line 30

The legacy env alias already handles `BATTLENET_COOKIE` for the CLI. Add stderr logging when it's used.

---

### Phase 3: Systematic Dev-vs-Frozen Parity

Prevent future "works on dev, breaks on frozen" regressions with infrastructure, not vigilance.

#### 3A. `BAKLOG_DEV_FROZEN_PARITY=1` mode

**File**: [`shared/install_paths.py`](shared/install_paths.py) + [`server.py`](server.py)

A single env var that makes dev behave like frozen:

| Aspect                 | Normal Dev            | `BAKLOG_DEV_FROZEN_PARITY=1`                     |
| ---------------------- | --------------------- | ------------------------------------------------ |
| `is_frozen()`          | `False`               | `True` (patched)                                 |
| Frontend               | Raw ESM modules       | Built `dist/` (`BAKLOG_SERVE_BUILT=1`)           |
| Data root              | Repo root             | Temp dir simulating `%LOCALAPPDATA%\BAKLOG-Data` |
| `/api/config` `frozen` | `false`               | `true`                                           |
| Profile paths          | `ROOT/cache/auth/...` | `<temp>/profiles/<id>/cache/auth/...`            |

Implementation: A new module `shared/dev_frozen_parity.py` that monkeypatches `is_frozen`, `data_root`, and `serve_built_frontend` when the env var is set. Called early in `server.py` startup.

Add to `startup.py` so `tray_app.py` also respects it, and add a JS-side detection so the frontend behaves correctly.

#### 3B. Extend CI to test frozen parity mode

**File**: New test in `tests/` or new script

Run the full test suite with `BAKLOG_DEV_FROZEN_PARITY=1`:

- Existing Python tests should pass
- Frontend integration tests should work with built dist/

Add to `scripts/test-all.ps1` as an optional step.

#### 3C. Connect-flow smoke test for frozen builds

**File**: New script `scripts/frozen_connect_smoke.py`

After `build_windows.ps1` creates the frozen bundle, run a smoke test that:

1. Starts the frozen server (with `BAKLOG_NO_BROWSER=1`)
2. Hits the connect endpoint for each browser-based provider (`/api/connect?provider=battlenet`)
3. Verifies the response doesn't contain fatal errors
4. Verifies the server stays alive (the connect attempt doesn't crash it)

Note: We can't actually sign in (no browser), but we CAN verify that the connect flow starts without crashing.

#### 3D. Audit existing frozen-only code paths

Search for `is_frozen()` calls across the codebase and document every dev-vs-frozen branch. Create a checklist in `docs/frozen-parity-checklist.md` that must be verified for each release.

Key files to audit:

- [`shared/install_paths.py`](shared/install_paths.py) — path resolution
- [`server.py`](server.py) — frontend serving mode, update checks
- [`shared/server_static.py`](shared/server_static.py) — static file serving
- [`shared/update_manager.py`](shared/update_manager.py) — update blocked when not frozen
- [`shared/startup.py`](shared/startup.py) — tray/server launch
- [`shared/server_support.py`](shared/server_support.py) — temp dir detection

#### 3E. Add `frozen_import_smoke.py` to build pipeline

**File**: [`scripts/frozen_bundle_smoke.py`](scripts/frozen_bundle_smoke.py)

Currently `frozen_import_smoke.py` exists but is NOT called from `build_windows.ps1`. Add it as a post-build step. This catches missing PyInstaller hidden imports before the build ships.

---

### Phase 4: Frontend Resilience (User-Facing)

Even when the backend connect flow has an unexpected error, the frontend should show a meaningful message instead of just "window disappeared."

#### 4A. Surface connect errors more clearly

**File**: [`js/connections.js`](js/connections.js)

When the SSE stream emits an `error` event, show a toast or inline error that explains what happened. Currently the window just vanishes and the chip goes back to "disconnected."

#### 4B. Add a "Show console" link for frozen builds

**File**: [`index.html`](index.html) or [`js/connections.js`](js/connections.js)

On frozen builds (detected via `/api/config` `frozen: true`), add a small note in the Connections tab: "If the sign-in window closes unexpectedly, check the BAKLOG server console for error details."

---

## Implementation Order

| Step   | What                                            | Effect                                                                    |
| ------ | ----------------------------------------------- | ------------------------------------------------------------------------- |
| **1A** | Add stderr logging to `run_connect_poll`        | Captures the actual error on next frozen build run                        |
| **1B** | Defensive import in `extract_battlenet_session` | May fix the immediate Battle.net issue                                    |
| **2A** | Make `run_connect_poll` exception-resilient     | Prevents ANY check failure from killing the browser (not just Battle.net) |
| **1C** | Admin frozen-diag endpoint                      | Visibility into frozen environment differences                            |
| **3A** | `BAKLOG_DEV_FROZEN_PARITY=1`                    | Lets developers reproduce frozen behavior in dev                          |
| **3B** | CI parity testing                               | Catches regressions before shipping                                       |
| **3C** | Frozen connect smoke test                       | Verifies connect flows don't crash the server                             |
| **3E** | Add import smoke to build                       | Catches missing PyInstaller imports                                       |
| **3D** | Frozen parity audit checklist                   | Documentation for future releases                                         |
| **4A** | Frontend error surfacing                        | Better UX when things go wrong                                            |
| **4B** | Console guidance link                           | Helps users self-diagnose                                                 |

Steps 1A, 1B, and 2A should ship together as a single PR since they're closely related.

---

## Risk Assessment

| Risk                                                                      | Mitigation                                                                                                                                                                         |
| ------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `run_connect_poll` catching too broadly masks real bugs                   | Log to stderr AND emit to session so the frontend shows the error. The 300s timeout still applies.                                                                                 |
| `BAKLOG_DEV_FROZEN_PARITY` diverges from actual frozen behavior over time | Keep the monkeypatches minimal (just `is_frozen`, `data_root`, `serve_built_frontend`). Add a test that compares `/api/config` output between parity mode and actual frozen build. |
| Connect smoke test adds build time                                        | Make it optional (`--smoke` flag) or keep it fast (no browser launch needed).                                                                                                      |
