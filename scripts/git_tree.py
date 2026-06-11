#!/usr/bin/env python3
"""Snapshot the local git "family tree" to a self-contained HTML page.

Runs read-only git plumbing (plus ``gh`` when available) and emits
``tracker-git.html`` at the repo root: a header card, a branch table with
ahead/behind-vs-main bars and open-PR badges, and an SVG commit graph
(GitHub-network style) with a ``git log --graph`` text fallback.

The output embeds its snapshot JSON inline and pulls in no CDN assets, so it
works fully offline when opened as ``file://``.

Usage (Windows):
  .\\.venv\\Scripts\\python.exe scripts\\git_tree.py             # write tracker-git.html
  .\\.venv\\Scripts\\python.exe scripts\\git_tree.py --fragment  # print inner HTML to stdout
  .\\.venv\\Scripts\\python.exe scripts\\git_tree.py -o out.html # custom output path
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_NAME = "tracker-git.html"
MAX_COMMITS = 300
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_UNIT = "\x1f"  # field separator inside a git --format record


def git(*args: str) -> str:
    """Run a read-only git command in the repo, returning trimmed stdout.

    Never raises: a failing/aborted git call degrades to an empty string so a
    partial repo state still produces a useful page.
    """
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_NO_WINDOW,
        )
    except (OSError, ValueError):
        return ""
    if proc.returncode != 0:
        return ""
    return (proc.stdout or "").strip()


def parse_ahead_behind(raw: str) -> dict[str, int]:
    """Parse ``git rev-list --left-right --count base...branch`` output.

    Left count is commits on base missing from the branch (behind); right is
    branch-only commits (ahead). Malformed input degrades to zeroes.
    """
    parts = raw.split()
    if len(parts) != 2:
        return {"behind": 0, "ahead": 0}
    try:
        behind, ahead = int(parts[0]), int(parts[1])
    except ValueError:
        return {"behind": 0, "ahead": 0}
    return {"behind": behind, "ahead": ahead}


def detect_base() -> str:
    """Pick the integration branch to compare against (main, else master)."""
    for candidate in ("main", "master"):
        if git("rev-parse", "--verify", "--quiet", f"refs/heads/{candidate}"):
            return candidate
    current = git("branch", "--show-current")
    return current or "main"


def parse_branch_row(line: str) -> dict[str, Any] | None:
    """Parse one for-each-ref record into a branch dict (tolerates blanks)."""
    if not line:
        return None
    fields = line.split(_UNIT)
    # name, sha, upstream, committerdate, subject, author
    fields += [""] * (6 - len(fields))
    name = fields[0].strip()
    if not name:
        return None
    return {
        "name": name,
        "sha": fields[1].strip(),
        "upstream": fields[2].strip(),
        "date": fields[3].strip(),
        "subject": fields[4].strip(),
        "author": fields[5].strip(),
    }


def collect_branches(base: str, current: str) -> list[dict[str, Any]]:
    fmt = _UNIT.join(
        [
            "%(refname:short)",
            "%(objectname:short)",
            "%(upstream:short)",
            "%(committerdate:iso8601)",
            "%(contents:subject)",
            "%(authorname)",
        ]
    )
    rows: list[dict[str, Any]] = []
    for line in git("for-each-ref", f"--format={fmt}", "refs/heads").splitlines():
        row = parse_branch_row(line)
        if not row:
            continue
        row["current"] = row["name"] == current
        if row["name"] == base:
            row["ahead"] = 0
            row["behind"] = 0
        else:
            counts = parse_ahead_behind(
                git("rev-list", "--left-right", "--count", f"{base}...{row['name']}")
            )
            row["ahead"] = counts["ahead"]
            row["behind"] = counts["behind"]
        rows.append(row)
    rows.sort(key=lambda r: (not r["current"], r["name"] != base, r["name"].lower()))
    return rows


def collect_remotes() -> list[dict[str, Any]]:
    fmt = _UNIT.join(
        [
            "%(refname:short)",
            "%(objectname:short)",
            "%(committerdate:iso8601)",
            "%(contents:subject)",
        ]
    )
    out: list[dict[str, Any]] = []
    for line in git("for-each-ref", f"--format={fmt}", "refs/remotes").splitlines():
        fields = line.split(_UNIT)
        fields += [""] * (4 - len(fields))
        name = fields[0].strip()
        if not name or name.endswith("/HEAD"):
            continue
        out.append(
            {
                "name": name,
                "sha": fields[1].strip(),
                "date": fields[2].strip(),
                "subject": fields[3].strip(),
            }
        )
    return out


def collect_commits(limit: int = MAX_COMMITS) -> list[dict[str, Any]]:
    """Structured commits (newest first) for the SVG graph renderer."""
    fmt = _UNIT.join(["%h", "%p", "%D", "%s", "%an", "%aI"])
    raw = git(
        "log",
        "--all",
        "--date-order",
        f"--format={fmt}",
        f"-n{limit}",
    )
    commits: list[dict[str, Any]] = []
    for line in raw.splitlines():
        if not line:
            continue
        fields = line.split(_UNIT)
        fields += [""] * (6 - len(fields))
        parents = [p for p in fields[1].split() if p]
        refs = [r.strip() for r in fields[2].split(",") if r.strip()]
        commits.append(
            {
                "sha": fields[0].strip(),
                "parents": parents,
                "refs": refs,
                "subject": fields[3].strip(),
                "author": fields[4].strip(),
                "date": fields[5].strip(),
            }
        )
    return commits


def collect_graph_text(limit: int = MAX_COMMITS) -> str:
    """The classic ``git log --graph`` ASCII tree (guaranteed fallback)."""
    return git(
        "log",
        "--graph",
        "--oneline",
        "--all",
        "--decorate",
        "--date-order",
        f"-n{limit}",
    )


def collect_prs() -> dict[str, Any]:
    """Open PRs via the gh CLI. Degrades to empty when gh is missing/unauthed."""
    if shutil.which("gh") is None:
        return {"available": False, "items": []}
    try:
        proc = subprocess.run(
            [
                "gh",
                "pr",
                "list",
                "--state",
                "open",
                "--json",
                "number,title,headRefName,baseRefName,isDraft,url,updatedAt",
                "--limit",
                "100",
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_NO_WINDOW,
        )
    except (OSError, ValueError):
        return {"available": False, "items": []}
    if proc.returncode != 0 or not (proc.stdout or "").strip():
        # gh present but not authed / no repo / no PRs distinguishable only by code;
        # treat non-zero as "unavailable" but empty success as available+empty.
        if proc.returncode != 0:
            return {"available": False, "items": []}
        return {"available": True, "items": []}
    try:
        items = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"available": False, "items": []}
    return {"available": True, "items": items if isinstance(items, list) else []}


def build_snapshot() -> dict[str, Any]:
    base = detect_base()
    current = git("branch", "--show-current")
    porcelain = git("status", "--porcelain")
    dirty_lines = [ln for ln in porcelain.splitlines() if ln.strip()]
    return {
        "generated_at": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "repo": ROOT.name,
        "base": base,
        "current": current,
        "dirty": bool(dirty_lines),
        "dirty_count": len(dirty_lines),
        "branches": collect_branches(base, current),
        "remotes": collect_remotes(),
        "commits": collect_commits(),
        "graph_text": collect_graph_text(),
        "prs": collect_prs(),
        "max_commits": MAX_COMMITS,
    }


# --- rendering -------------------------------------------------------------

_FRAGMENT_TEMPLATE = """<section class="git-tree" id="git-tree-root">
  <div id="git-tree-mount"></div>
  <script type="application/json" id="git-tree-data">__DATA__</script>
  <script>__SCRIPT__</script>
</section>"""


def _render_script() -> str:
    """The client renderer: builds header, branch table, and SVG commit graph."""
    return r"""
(function () {
  var rootEl = document.getElementById("git-tree-data");
  if (!rootEl) return;
  var data;
  try { data = JSON.parse(rootEl.textContent || "{}"); }
  catch (e) { data = {}; }
  var mount = document.getElementById("git-tree-mount");
  if (!mount) return;

  var PALETTE = ["#38bdf8","#a78bfa","#34d399","#fbbf24","#f472b6",
                 "#f87171","#60a5fa","#4ade80","#fb923c","#c084fc"];
  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  function ago(iso) {
    if (!iso) return "";
    var t = Date.parse(iso);
    if (isNaN(t)) return "";
    var s = Math.max(0, (Date.now() - t) / 1000);
    var u = [["y",31536000],["mo",2592000],["d",86400],["h",3600],["m",60]];
    for (var i = 0; i < u.length; i++) {
      var n = Math.floor(s / u[i][1]);
      if (n >= 1) return n + u[i][0] + " ago";
    }
    return "just now";
  }

  // --- PR index by head branch ---
  var prs = (data.prs && data.prs.items) || [];
  var prByHead = {};
  prs.forEach(function (p) { if (p.headRefName) prByHead[p.headRefName] = p; });

  // --- header ---
  var branches = data.branches || [];
  var header = document.createElement("div");
  header.className = "gt-header";
  var dirtyBadge = data.dirty
    ? '<span class="gt-badge gt-badge-warn">' + data.dirty_count + " uncommitted</span>"
    : '<span class="gt-badge gt-badge-ok">clean</span>';
  var aheadTotal = branches.reduce(function (a, b) { return a + (b.ahead || 0); }, 0);
  header.innerHTML =
    '<div class="gt-title">' + esc(data.repo || "repo") + " &middot; git family tree</div>" +
    '<div class="gt-meta">' +
      '<span class="gt-badge gt-badge-cur">&#9733; ' + esc(data.current || "(detached)") + "</span>" +
      dirtyBadge +
      '<span class="gt-pill">' + branches.length + " branches</span>" +
      '<span class="gt-pill">' + aheadTotal + " commits ahead of " + esc(data.base) + "</span>" +
      '<span class="gt-pill">' + prs.length + " open PRs</span>" +
    "</div>" +
    '<div class="gt-gen">Generated ' + esc(data.generated_at || "") +
      ' &middot; regen: <code>.\\.venv\\Scripts\\python.exe scripts\\git_tree.py</code></div>';
  mount.appendChild(header);

  // --- usage instructions ---
  var howto = document.createElement("details");
  howto.className = "gt-howto";
  howto.open = true;
  howto.innerHTML =
    "<summary>How to use this page</summary>" +
    '<div class="gt-howto-body">' +
      "<p>This page is a static snapshot \u2014 it does <strong>not</strong> update on its own. " +
      "Re-run the script, then refresh the browser tab.</p>" +
      "<ol>" +
        "<li><strong>Regenerate the snapshot</strong> (from the repo root, Windows):<br>" +
          "<code>.\\.venv\\Scripts\\python.exe scripts\\git_tree.py</code></li>" +
        "<li><strong>Refresh this page</strong> in your browser: " +
          "<kbd>F5</kbd> (or <kbd>Ctrl</kbd>+<kbd>R</kbd>; " +
          "<kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>R</kbd> to hard-refresh).</li>" +
      "</ol>" +
      "<p class=\"gt-howto-note\">Options: <code>--fragment</code> prints the inner HTML for embedding in " +
      "<code>tracker.html</code>; <code>-o &lt;path&gt;</code> writes to a custom file. " +
      "PR badges require the <code>gh</code> CLI installed and authenticated.</p>" +
    "</div>";
  mount.appendChild(howto);

  if (!data.prs || data.prs.available === false) {
    var note = document.createElement("div");
    note.className = "gt-ghnote";
    note.textContent =
      "PR data unavailable (gh CLI not installed or not authenticated) " +
      "\u2014 branch tree shown without PR badges.";
    mount.appendChild(note);
  }

  // --- branch table ---
  var table = document.createElement("table");
  table.className = "gt-table";
  table.innerHTML =
    "<thead><tr><th>Branch</th><th>vs " + esc(data.base) +
    "</th><th>Last commit</th><th>Age</th><th>Upstream</th><th>PR</th></tr></thead>";
  var tbody = document.createElement("tbody");
  branches.forEach(function (b) {
    var tr = document.createElement("tr");
    if (b.current) tr.className = "gt-row-cur";
    var ahead = b.ahead || 0, behind = b.behind || 0;
    var bars =
      '<span class="gt-ahead">' + (ahead ? "+" + ahead : "") + "</span>" +
      '<span class="gt-behind">' + (behind ? "\u2212" + behind : "") + "</span>" +
      (ahead === 0 && behind === 0 ? '<span class="gt-even">in sync</span>' : "");
    var pr = prByHead[b.name];
    var prCell = pr
      ? '<a class="gt-pr' + (pr.isDraft ? " gt-pr-draft" : "") + '" href="' +
        esc(pr.url) + '" target="_blank" rel="noopener">#' + esc(pr.number) +
        (pr.isDraft ? " draft" : "") + "</a>"
      : '<span class="gt-dim">\u2014</span>';
    tr.innerHTML =
      "<td>" + (b.current ? "&#9733; " : "") + '<span class="gt-bname">' + esc(b.name) + "</span></td>" +
      '<td class="gt-vs">' + bars + "</td>" +
      '<td class="gt-subj" title="' + esc(b.subject) + '"><code>' + esc(b.sha) + "</code> " + esc(b.subject) + "</td>" +
      "<td>" + esc(ago(b.date)) + "</td>" +
      "<td>" + (
        b.upstream
          ? '<span class="gt-dim">' + esc(b.upstream) + "</span>"
          : '<span class="gt-warn">none</span>'
      ) + "</td>" +
      "<td>" + prCell + "</td>";
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  mount.appendChild(table);

  // --- SVG commit graph (lane assignment) ---
  var commits = data.commits || [];
  var graphWrap = document.createElement("div");
  graphWrap.className = "gt-graph-wrap";
  if (commits.length) {
    var lanes = [];
    var pos = {};
    function freeLane() {
      var i = lanes.indexOf(null);
      if (i === -1) { i = lanes.length; lanes.push(null); }
      return i;
    }
    function dedupe() {
      for (var a = 0; a < lanes.length; a++) {
        if (lanes[a] === null) continue;
        for (var b = a + 1; b < lanes.length; b++) {
          if (lanes[b] === lanes[a]) lanes[b] = null;
        }
      }
    }
    var maxCol = 0;
    commits.forEach(function (c, row) {
      var col = lanes.indexOf(c.sha);
      if (col === -1) { col = freeLane(); lanes[col] = c.sha; }
      pos[c.sha] = { col: col, row: row };
      if (col > maxCol) maxCol = col;
      var parents = c.parents || [];
      if (parents.length === 0) {
        lanes[col] = null;
      } else {
        lanes[col] = parents[0];
        for (var k = 1; k < parents.length; k++) {
          if (lanes.indexOf(parents[k]) === -1) lanes[freeLane()] = parents[k];
        }
      }
      dedupe();
    });

    var COLW = 18, ROWH = 30, PADX = 14, PADY = 18, R = 5;
    var graphW = PADX * 2 + (maxCol + 1) * COLW;
    var textX = graphW + 8;
    var height = PADY * 2 + commits.length * ROWH;
    function cx(col) { return PADX + col * COLW; }
    function cy(row) { return PADY + row * ROWH; }

    var svgNS = "http://www.w3.org/2000/svg";
    var svg = document.createElementNS(svgNS, "svg");
    svg.setAttribute("class", "gt-svg");
    svg.setAttribute("height", height);
    svg.setAttribute("width", "100%");
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", "commit graph");

    // edges first (under nodes)
    commits.forEach(function (c) {
      var p = pos[c.sha];
      (c.parents || []).forEach(function (par) {
        var pp = pos[par];
        if (!pp) return;
        var x1 = cx(p.col), y1 = cy(p.row), x2 = cx(pp.col), y2 = cy(pp.row);
        var path = document.createElementNS(svgNS, "path");
        var d;
        if (x1 === x2) {
          d = "M" + x1 + "," + y1 + " L" + x2 + "," + y2;
        } else {
          var my = (y1 + y2) / 2;
          d = "M" + x1 + "," + y1 + " C" + x1 + "," + my + " " + x2 + "," + my + " " + x2 + "," + y2;
        }
        path.setAttribute("d", d);
        path.setAttribute("class", "gt-edge");
        path.setAttribute("stroke", PALETTE[pp.col % PALETTE.length]);
        svg.appendChild(path);
      });
    });

    // nodes + labels
    commits.forEach(function (c) {
      var p = pos[c.sha];
      var color = PALETTE[p.col % PALETTE.length];
      var circ = document.createElementNS(svgNS, "circle");
      circ.setAttribute("cx", cx(p.col));
      circ.setAttribute("cy", cy(p.row));
      circ.setAttribute("r", R);
      circ.setAttribute("fill", color);
      circ.setAttribute("class", "gt-node");
      svg.appendChild(circ);

      var label = document.createElementNS(svgNS, "text");
      label.setAttribute("x", textX);
      label.setAttribute("y", cy(p.row) + 4);
      label.setAttribute("class", "gt-svg-text");
      var tspanSha = document.createElementNS(svgNS, "tspan");
      tspanSha.setAttribute("class", "gt-svg-sha");
      tspanSha.textContent = c.sha + " ";
      label.appendChild(tspanSha);
      (c.refs || []).forEach(function (r) {
        var t = document.createElementNS(svgNS, "tspan");
        t.setAttribute("class", "gt-svg-ref");
        t.textContent = "(" + r + ") ";
        label.appendChild(t);
      });
      var tspanSub = document.createElementNS(svgNS, "tspan");
      tspanSub.textContent = c.subject;
      label.appendChild(tspanSub);
      svg.appendChild(label);
    });

    graphWrap.appendChild(svg);
  } else {
    graphWrap.innerHTML = '<div class="gt-dim">No commits found.</div>';
  }
  var graphHeading = document.createElement("h2");
  graphHeading.className = "gt-h2";
  graphHeading.textContent = "Commit graph (newest first, up to " + (data.max_commits || 0) + ")";
  mount.appendChild(graphHeading);
  mount.appendChild(graphWrap);

  // --- text fallback ---
  if (data.graph_text) {
    var details = document.createElement("details");
    details.className = "gt-fallback";
    var summary = document.createElement("summary");
    summary.textContent = "Text graph (git log --graph)";
    details.appendChild(summary);
    var pre = document.createElement("pre");
    pre.textContent = data.graph_text;
    details.appendChild(pre);
    mount.appendChild(details);
  }
})();
"""


def render_fragment(snapshot: dict[str, Any]) -> str:
    payload = json.dumps(snapshot, ensure_ascii=False).replace("</", "<\\/")
    return _FRAGMENT_TEMPLATE.replace("__DATA__", payload).replace(
        "__SCRIPT__", _render_script()
    )


def render_html(snapshot: dict[str, Any]) -> str:
    fragment = render_fragment(snapshot)
    return f"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{snapshot.get("repo", "repo")} — git family tree</title>
<style>
:root {{
  --bg: #0f172a; --bg-panel: #1e293b; --bg-elev: #334155;
  --border: rgb(71 85 105); --border-subtle: rgb(51 65 85);
  --text: #e2e8f0; --text-bright: #f8fafc; --text-mute: #94a3b8;
  --accent: #38bdf8;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0; padding: 24px; background: var(--bg); color: var(--text);
  font: 14px/1.5 -apple-system, "Segoe UI", system-ui, sans-serif;
  color-scheme: dark;
}}
code, pre {{ font-family: "JetBrains Mono", Consolas, ui-monospace, monospace; }}
.git-tree {{ max-width: 1100px; margin: 0 auto; }}
.gt-header {{
  background: var(--bg-panel); border: 1px solid var(--border-subtle);
  border-radius: 12px; padding: 16px 20px; margin-bottom: 18px;
}}
.gt-title {{ font-size: 20px; font-weight: 700; color: var(--text-bright); }}
.gt-meta {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }}
.gt-gen {{ margin-top: 10px; color: var(--text-mute); font-size: 12px; }}
.gt-gen code {{ color: var(--accent); }}
.gt-badge, .gt-pill {{
  display: inline-block; padding: 2px 10px; border-radius: 999px;
  font-size: 12px; font-weight: 600;
}}
.gt-pill {{ background: var(--bg-elev); color: var(--text-dim); }}
.gt-badge-cur {{ background: color-mix(in srgb, var(--accent) 22%, transparent); color: var(--accent); }}
.gt-badge-ok {{ background: rgba(52, 211, 153, 0.18); color: #34d399; }}
.gt-badge-warn {{ background: rgba(251, 191, 36, 0.18); color: #fbbf24; }}
.gt-ghnote {{
  background: rgba(251, 191, 36, 0.1); border: 1px solid rgba(251, 191, 36, 0.3);
  color: #fbbf24; border-radius: 8px; padding: 8px 12px; margin-bottom: 16px; font-size: 13px;
}}
.gt-howto {{
  background: var(--bg-panel); border: 1px solid var(--border-subtle);
  border-radius: 12px; padding: 4px 20px; margin-bottom: 18px;
}}
.gt-howto > summary {{
  cursor: pointer; color: var(--text-bright); font-weight: 600;
  padding: 12px 0; list-style: none;
}}
.gt-howto > summary::-webkit-details-marker {{ display: none; }}
.gt-howto > summary::before {{ content: "\\25B8  "; color: var(--accent); }}
.gt-howto[open] > summary::before {{ content: "\\25BE  "; }}
.gt-howto-body {{ padding-bottom: 14px; color: var(--text); }}
.gt-howto-body p {{ margin: 8px 0; }}
.gt-howto-body ol {{ margin: 8px 0; padding-left: 22px; }}
.gt-howto-body li {{ margin: 6px 0; }}
.gt-howto-body code {{
  background: #0b1120; border: 1px solid var(--border-subtle); border-radius: 6px;
  padding: 1px 7px; color: var(--accent); font-size: 12.5px;
}}
.gt-howto-body kbd {{
  background: var(--bg-elev); border: 1px solid var(--border); border-radius: 5px;
  padding: 1px 6px; font-size: 12px; font-family: inherit; color: var(--text-bright);
  box-shadow: 0 1px 0 var(--border);
}}
.gt-howto-note {{ color: var(--text-mute); font-size: 13px; }}
.gt-table {{
  width: 100%; border-collapse: collapse; margin-bottom: 26px;
  background: var(--bg-panel); border-radius: 12px; overflow: hidden;
}}
.gt-table th, .gt-table td {{
  text-align: left; padding: 9px 14px; border-bottom: 1px solid var(--border-subtle);
  vertical-align: top;
}}
.gt-table th {{ color: var(--text-mute); font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }}
.gt-table tr:last-child td {{ border-bottom: none; }}
.gt-row-cur {{ background: color-mix(in srgb, var(--accent) 8%, transparent); }}
.gt-bname {{ color: var(--text-bright); font-weight: 600; }}
.gt-subj {{ max-width: 420px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.gt-subj code {{ color: var(--accent); margin-right: 6px; }}
.gt-ahead {{ color: #34d399; font-weight: 700; margin-right: 6px; }}
.gt-behind {{ color: #fbbf24; font-weight: 700; }}
.gt-even, .gt-dim {{ color: var(--text-mute); }}
.gt-warn {{ color: #fbbf24; }}
.gt-pr {{
  display: inline-block; padding: 1px 8px; border-radius: 6px; text-decoration: none;
  background: color-mix(in srgb, var(--accent) 18%, transparent); color: var(--accent); font-weight: 600;
}}
.gt-pr-draft {{ background: var(--bg-elev); color: var(--text-mute); }}
.gt-h2 {{
  font-size: 15px; color: var(--text-mute); text-transform: uppercase;
  letter-spacing: .04em; margin: 0 0 8px;
}}
.gt-graph-wrap {{
  background: var(--bg-panel); border: 1px solid var(--border-subtle);
  border-radius: 12px; padding: 8px 4px; overflow-x: auto;
}}
.gt-svg {{ display: block; }}
.gt-edge {{ fill: none; stroke-width: 2; opacity: 0.85; }}
.gt-node {{ stroke: var(--bg-panel); stroke-width: 2; }}
.gt-svg-text {{ fill: var(--text); font: 12px Consolas, ui-monospace, monospace; }}
.gt-svg-sha {{ fill: var(--accent); }}
.gt-svg-ref {{ fill: #fbbf24; font-weight: 700; }}
.gt-fallback {{ margin-top: 18px; }}
.gt-fallback summary {{ cursor: pointer; color: var(--text-mute); padding: 6px 0; }}
.gt-fallback pre {{
  background: #0b1120; border: 1px solid var(--border-subtle); border-radius: 8px;
  padding: 12px; overflow-x: auto; font-size: 12px; color: var(--text-dim);
}}
</style>
</head>
<body>
{fragment}
</body>
</html>
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Snapshot the git family tree to HTML.")
    parser.add_argument(
        "--fragment",
        action="store_true",
        help="Print only the inner HTML section (for embedding into tracker.html).",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help=f"Output path for the full page (default: {OUTPUT_NAME} at repo root).",
    )
    args = parser.parse_args(argv)

    snapshot = build_snapshot()

    if args.fragment:
        sys.stdout.write(render_fragment(snapshot))
        return 0

    out_path = Path(args.output) if args.output else (ROOT / OUTPUT_NAME)
    out_path.write_text(render_html(snapshot), encoding="utf-8")
    n_branches = len(snapshot["branches"])
    n_commits = len(snapshot["commits"])
    print(f"Wrote {out_path} ({n_branches} branches, {n_commits} commits).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
