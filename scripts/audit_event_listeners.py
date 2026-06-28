import json
import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS_GLOB = ["js/**/*.js", "landing/**/*.js"]
HTML_PATHS = [ROOT / "index.html", ROOT / "landing/index.html"]
LISTENER_RE = re.compile(
    "(?P<target>document|window|globalThis|[\\w.$]+)\\.addEventListener\\(\\s*['\\\"](?P<event>[^'\\\"]+)['\\\"]"
)
DISPATCH_RE = re.compile(
    "(?P<target>document|window)\\.dispatchEvent\\(\\s*(?:new\\s+CustomEvent\\(\\s*['\\\"](?P<custom>[^'\\\"]+)['\\\"]|new\\s+Event\\(\\s*['\\\"](?P<plain>[^'\\\"]+)['\\\"])"
)
CONFIGURE_RE = re.compile("export function (configure\\w+)\\(")
DEBOUNCE_RE = re.compile("(?:setTimeout|_debounce|DEBOUNCE|PUSH_DEBOUNCE|_filterDebounceTimer|POLL_MS)")
ENRICH_CACHE_LOADERS = {
    "hltb": "loadHltbCache",
    "steamReviews": "loadSteamReviewCache",
    "steamCovers": "loadSteamCoversMeta",
    "steamTags": "loadSteamTagsMeta",
    "protondb": "loadProtondbCache",
}


def _iter_js_files():
    out = []
    for pattern in JS_GLOB:
        out.extend(ROOT.glob(pattern))
    return sorted({p.resolve() for p in out if p.is_file()})


def _line_no(text, pos):
    return text.count("\n", 0, pos) + 1


def scan_js(path):
    text = path.read_text(encoding="utf-8")
    rel = path.relative_to(ROOT).as_posix()
    listeners = []
    for m in LISTENER_RE.finditer(text):
        listeners.append(
            {"file": rel, "line": _line_no(text, m.start()), "target": m.group("target"), "event": m.group("event")}
        )
    dispatches = []
    for m in DISPATCH_RE.finditer(text):
        dispatches.append(
            {
                "file": rel,
                "line": _line_no(text, m.start()),
                "target": m.group("target"),
                "event": m.group("custom") or m.group("plain"),
            }
        )
    configures = [m.group(1) for m in CONFIGURE_RE.finditer(text)]
    has_debounce = bool(DEBOUNCE_RE.search(text))
    return {
        "listeners": listeners,
        "dispatches": dispatches,
        "configure_exports": configures,
        "has_debounce": has_debounce,
    }


def scan_reload_after_fetcher():
    path = ROOT / "js" / "library-load.js"
    text = path.read_text(encoding="utf-8")
    branch = re.search("export async function reloadAfterFetcher\\(key\\)\\s*\\{([\\s\\S]*?)^\\}", text, re.MULTILINE)
    body = branch.group(1) if branch else ""
    enrich_branch = re.search("ENRICH_FETCHER_KEYS\\.has\\(key\\)\\)\\s*\\{([\\s\\S]*?)\\} else if", body)
    enrich_body = enrich_branch.group(1) if enrich_branch else ""
    cache_loaders = {}
    gaps = []
    for key, fn in ENRICH_CACHE_LOADERS.items():
        present = fn in enrich_body
        cache_loaders[key] = present
        if not present:
            gaps.append(f"{key}: missing {fn}() in enrich branch")
    return {"enrich_cache_loaders": cache_loaders, "gaps": gaps}


def build_custom_event_index(scans):
    emitters = defaultdict(list)
    listeners = defaultdict(list)
    for data in scans.values():
        for d in data["dispatches"]:
            emitters[d["event"]].append(f"{d['file']}:{d['line']}")
        for ln in data["listeners"]:
            if ln["event"].startswith("baklog:") or ln["event"] in ("visibilitychange", "themechange"):
                listeners[ln["event"]].append(f"{ln['file']}:{ln['line']} ({ln['target']})")
    orphan_emit = {ev: locs for ev, locs in emitters.items() if ev.startswith("baklog:") and ev not in listeners}
    orphan_listen = {ev: locs for ev, locs in listeners.items() if ev.startswith("baklog:") and ev not in emitters}
    return {
        "emitters": dict(emitters),
        "listeners": dict(listeners),
        "orphan_emitters": orphan_emit,
        "orphan_listeners": orphan_listen,
    }


def main():
    scans = {}
    total_listeners = 0
    for path in _iter_js_files():
        rel = path.relative_to(ROOT).as_posix()
        scans[rel] = scan_js(path)
        total_listeners += len(scans[rel]["listeners"])
    custom_index = build_custom_event_index(scans)
    reload_audit = scan_reload_after_fetcher()
    debounce_files = sorted((k for k, v in scans.items() if v["has_debounce"]))
    configure_all = sorted({fn for v in scans.values() for fn in v["configure_exports"]})
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "summary": {
            "js_files_scanned": len(scans),
            "dom_listeners": total_listeners,
            "custom_events": len([e for e in custom_index["emitters"] if e.startswith("baklog:")]),
            "configure_registries": configure_all,
            "reload_gaps": reload_audit["gaps"],
        },
        "custom_events": custom_index,
        "reload_after_fetcher": reload_audit,
        "debounce_modules": debounce_files,
        "per_file": {
            k: {
                "listener_count": len(v["listeners"]),
                "dispatch_count": len(v["dispatches"]),
                "configure_exports": v["configure_exports"],
            }
            for k, v in scans.items()
        },
    }
    json_path = ROOT / "EVENT_AUDIT.json"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_lines = [
        "# BAKLOG event & listener audit",
        "",
        f"Generated: {report['generated_at']}",
        "",
        "## Summary",
        "",
        f"- JS files scanned: **{report['summary']['js_files_scanned']}**",
        f"- DOM `addEventListener` calls: **{report['summary']['dom_listeners']}**",
        f"- Callback registries: `{', '.join(configure_all) or 'none'}`",
        "",
        "## Custom events (`baklog:*`)",
        "",
    ]
    for ev in sorted(e for e in custom_index["emitters"] if e.startswith("baklog:")):
        md_lines.append(f"### `{ev}`")
        md_lines.append(f"- Emitters: {', '.join(custom_index['emitters'].get(ev, []))}")
        md_lines.append(f"- Listeners: {', '.join(custom_index['listeners'].get(ev, [])) or '_none_'}")
        md_lines.append("")
    md_lines.extend(
        [
            "## reloadAfterFetcher enrich cache loaders",
            "",
            "| Key | Loader called after enrich |",
            "|-----|---------------------------|",
        ]
    )
    for key, ok in reload_audit["enrich_cache_loaders"].items():
        md_lines.append(f"| {key} | {('yes' if ok else '**NO**')} |")
    if reload_audit["gaps"]:
        md_lines.extend(["", "### Gaps", ""])
        for g in reload_audit["gaps"]:
            md_lines.append(f"- {g}")
    md_lines.extend(
        [
            "",
            "## Data-arrival propagation chain",
            "",
            "```",
            "POST /api/run/<key> → SSE done → fetcherRunner.refreshAfterFetch",
            "  → reloadAfterFetcher(key) → applyMergedLibrary → refreshLibraryChromeAfterMerge",
            "  → (dashboard) scheduleDashboardRender | (library) refreshFilterUI + renderTable",
            "  → (connections) defer* → flushDeferredRenders on switchView",
            "```",
            "",
            "## Debounce modules (sample)",
            "",
        ]
    )
    for f in debounce_files[:20]:
        md_lines.append(f"- `{f}`")
    if len(debounce_files) > 20:
        md_lines.append(f"- … and {len(debounce_files) - 20} more")
    merge_fn = (ROOT / "js" / "library-load.js").read_text(encoding="utf-8")
    double_chrome = (
        "renderSummary()" in merge_fn
        and re.search("renderSummary\\(\\)[\\s\\S]{0,120}refreshFilterUI", merge_fn) is not None
    )
    md_lines.extend(
        [
            "",
            "## Phase 2 efficiency (2026-06-08)",
            "",
            f"- Double summary/picks paint before refreshFilterUI: **{('FAIL' if double_chrome else 'ok')}**",
            f"- Enrich wishlist reload scoped via ENRICH_RELOAD_WISHLIST_KEYS: **{('yes' if 'ENRICH_RELOAD_WISHLIST_KEYS' in merge_fn else 'no')}**",
            "- Propagation counters: `?debug=1` → debug overlay `prop` row + `window.__baklogProp`",
            "",
            "## Phase 3 correctness (2026-06-08)",
            "",
            "- `js/custom-events.js` — canonical baklog:* registry (name, target, emitters, listeners)",
            "- Cross-tab personal sync via `storage` event (`installPersonalStorageSync`) — server-only multi-tab still deferred",
            "- Profile switch: `location.reload()` + `prepareForProfileSwitch` — full teardown, no orphan SSE",
            "- `flushDeferredRenders`: defer consume until table view (flags survive dashboard hop)",
            "- `bindEvents`: `_eventsBound` guard",
            "",
            "## Phase 4 instrumentation (2026-06-08)",
            "",
            "- `js/propagation-scenarios.js` — 10-scenario manual verification matrix",
            "- Extended `js/propagation-trace.js`: fetcherReloads, downstreamSyncs, deferredDefers, deferredFlushes",
            "- Hooks: reloadAfterFetcher, render-gate defer*, flushDeferredRenders, scheduleDownstreamSync",
            "- Debug overlay `prop` row: M/T/S/R/D/def/fl; bug bundle includes `runtime.propagation`",
            "- Tests: `tests/propagation-scenarios.test.js`",
            "",
            "## Phase 5 scenario matrix (2026-06-08)",
            "",
            "- `tests/scenario-matrix.test.js` — 10 user-flow scenarios driven against real seams",
            "- 1 PSN pull · 2 HLTB enrich · 3 status edit · 4 GOG auto-fetch · 5 profile switch",
            "- 6 tab backgrounded · 7 ITAD sale · 8 claims · 9 theme toggle · 10 deep-sync",
            "- 12 Vitest green (routing, downstream sync, diff fns, visibility, custom events)",
            "",
            "## Phase 6 remediation tiers (2026-06-08)",
            "",
            "Decision-record pass — P0/P1 substance already shipped (EVT-01/05/06/07/08). Remaining P2s resolved as document/defer; no production code change.",
            "",
            "- EVT-02 → RESOLVED (documented): window vs document targets are intentional and captured in js/custom-events.js BAKLOG_EVENT_REGISTRY (per-event `target`).",
            "- EVT-03 → DEFERRED (blocked): #region agent log blocks in app.js/bind-events.js/filters-ui.js/fetcher-health.js/picks-ui.js belong to the active picks-desync repro (find_picks_hidden_button_desync, still INVESTIGATING). Trigger: strip when that finding flips to RESOLVED.",
            "- EVT-04 remainder → DEFERRED (won't-fix-now): same-browser multi-tab covered by installPersonalStorageSync (LS storage event). Residual: two tabs + server-side change without an LS write could stale-overwrite. Cheap future option: visibility-triggered GET /api/personal re-pull on tab focus. Low value for a local single-user app.",
            "- P3 bind-events.js domain split + P4 baklog:library-merged event: OPTIONAL, deferred (no orphaned-listener bug observed; bindEvents is guarded against double-bind).",
            "",
            "## Findings log",
            "",
            "| ID | Tier | Finding | Status |",
            "|----|------|---------|--------|",
            "| EVT-01 | P1 | protondb enrich missing loadProtondbCache | FIXED |",
            "| EVT-05 | P1 | enrich reloaded all wishlist JSON every time | FIXED (scoped to hltb+steamCovers) |",
            "| EVT-06 | P1 | refreshLibraryChromeAfterMerge double-painted summary+picks | FIXED |",
            "| EVT-07 | P2 | flushDeferredRenders consumed flags on dashboard hop | FIXED |",
            "| EVT-08 | P2 | bindEvents double-registration risk | FIXED (guard) |",
            "| EVT-02 | P2 | baklog:themechange on window vs document | RESOLVED (documented) |",
            "| EVT-03 | P2 | stale agent log blocks (picks desync session) | DEFERRED (blocked on picks-desync repro) |",
            "| EVT-04 | P2 | no inbound personalStore sync | DEFERRED (LS storage shipped; server-push multi-tab won't-fix) |",
            "",
            "## Findings tier",
            "",
            "- **P0** Broken propagation (data arrives, visible UI stale)",
            "- **P1** Missing cache reload / redundant full-catalog fetch",
            "- **P2** Undocumented custom events / inconsistent document vs window target",
            "",
            "Re-run: `python scripts/audit_event_listeners.py`",
            "",
        ]
    )
    md_path = ROOT / "EVENT_AUDIT.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"Wrote {json_path.name} and {md_path.name}")
    if reload_audit["gaps"]:
        print("GAPS:", "; ".join(reload_audit["gaps"]))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
