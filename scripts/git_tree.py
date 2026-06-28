import argparse
import datetime as _dt
import html
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_NAME = "tracker-git.html"
MAX_COMMITS = 300
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_UNIT = "\x1f"


def git(*args):
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


def parse_ahead_behind(raw):
    parts = raw.split()
    if len(parts) != 2:
        return {"behind": 0, "ahead": 0}
    try:
        behind, ahead = (int(parts[0]), int(parts[1]))
    except ValueError:
        return {"behind": 0, "ahead": 0}
    return {"behind": behind, "ahead": ahead}


def detect_base():
    for candidate in ("main", "master"):
        if git("rev-parse", "--verify", "--quiet", f"refs/heads/{candidate}"):
            return candidate
    current = git("branch", "--show-current")
    return current or "main"


def parse_branch_row(line):
    if not line:
        return None
    fields = line.split(_UNIT)
    fields += [""] * (5 - len(fields))
    name = fields[0].strip()
    if not name:
        return None
    return {
        "name": name,
        "sha": fields[1].strip(),
        "upstream": fields[2].strip(),
        "date": fields[3].strip(),
        "subject": fields[4].strip(),
    }


def collect_branches(base, current):
    fmt = _UNIT.join(
        [
            "%(refname:short)",
            "%(objectname:short)",
            "%(upstream:short)",
            "%(committerdate:iso8601)",
            "%(contents:subject)",
        ]
    )
    rows = []
    for line in git("for-each-ref", f"--format={fmt}", "refs/heads").splitlines():
        row = parse_branch_row(line)
        if not row:
            continue
        row["current"] = row["name"] == current
        if row["name"] == base:
            row["ahead"] = 0
            row["behind"] = 0
        else:
            counts = parse_ahead_behind(git("rev-list", "--left-right", "--count", f"{base}...{row['name']}"))
            row["ahead"] = counts["ahead"]
            row["behind"] = counts["behind"]
        rows.append(row)
    rows.sort(key=lambda r: (not r["current"], r["name"] != base, r["name"].lower()))
    return rows


def collect_commits(limit=MAX_COMMITS):
    fmt = _UNIT.join(["%h", "%p", "%D", "%s", "%aI"])
    raw = git("log", "--all", "--date-order", f"--format={fmt}", f"-n{limit}")
    commits = []
    for line in raw.splitlines():
        if not line:
            continue
        fields = line.split(_UNIT)
        fields += [""] * (5 - len(fields))
        parents = [p for p in fields[1].split() if p]
        refs = [r.strip() for r in fields[2].split(",") if r.strip()]
        commits.append(
            {
                "sha": fields[0].strip(),
                "parents": parents,
                "refs": refs,
                "subject": fields[3].strip(),
                "date": fields[4].strip(),
            }
        )
    return commits


def collect_graph_text(limit=MAX_COMMITS):
    return git("log", "--graph", "--oneline", "--all", "--decorate", "--date-order", f"-n{limit}")


def collect_prs():
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
        if proc.returncode != 0:
            return {"available": False, "items": []}
        return {"available": True, "items": []}
    try:
        items = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"available": False, "items": []}
    return {"available": True, "items": items if isinstance(items, list) else []}


def build_snapshot():
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
        "commits": collect_commits(),
        "graph_text": collect_graph_text(),
        "prs": collect_prs(),
        "max_commits": MAX_COMMITS,
    }


_FRAGMENT_TEMPLATE = '<section class="git-tree" id="git-tree-root">\n  <div id="git-tree-mount"></div>\n  <script type="application/json" id="git-tree-data">__DATA__</script>\n  <script>__SCRIPT__</script>\n</section>'


def _render_script():
    return '\n(function () {\n  var rootEl = document.getElementById("git-tree-data");\n  if (!rootEl) return;\n  var data;\n  try { data = JSON.parse(rootEl.textContent || "{}"); }\n  catch (e) { data = {}; }\n  var mount = document.getElementById("git-tree-mount");\n  if (!mount) return;\n\n  var PALETTE = ["#38bdf8","#a78bfa","#34d399","#fbbf24","#f472b6",\n                 "#f87171","#60a5fa","#4ade80","#fb923c","#c084fc"];\n  function esc(s) {\n    return String(s == null ? "" : s)\n      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")\n      .replace(/"/g, "&quot;").replace(/\'/g, "&#39;");\n  }\n  function ago(iso) {\n    if (!iso) return "";\n    var t = Date.parse(iso);\n    if (isNaN(t)) return "";\n    var s = Math.max(0, (Date.now() - t) / 1000);\n    var u = [["y",31536000],["mo",2592000],["d",86400],["h",3600],["m",60]];\n    for (var i = 0; i < u.length; i++) {\n      var n = Math.floor(s / u[i][1]);\n      if (n >= 1) return n + u[i][0] + " ago";\n    }\n    return "just now";\n  }\n\n  // --- PR index by head branch ---\n  var prs = (data.prs && data.prs.items) || [];\n  var prByHead = {};\n  prs.forEach(function (p) { if (p.headRefName) prByHead[p.headRefName] = p; });\n\n  // --- header ---\n  var branches = data.branches || [];\n  var header = document.createElement("div");\n  header.className = "gt-header";\n  var dirtyBadge = data.dirty\n    ? \'<span class="gt-badge gt-badge-warn">\' + data.dirty_count + " uncommitted</span>"\n    : \'<span class="gt-badge gt-badge-ok">clean</span>\';\n  var aheadTotal = branches.reduce(function (a, b) { return a + (b.ahead || 0); }, 0);\n  header.innerHTML =\n    \'<div class="gt-title">\' + esc(data.repo || "repo") + " &middot; git family tree</div>" +\n    \'<div class="gt-meta">\' +\n      \'<span class="gt-badge gt-badge-cur">&#9733; \' + esc(data.current || "(detached)") + "</span>" +\n      dirtyBadge +\n      \'<span class="gt-pill">\' + branches.length + " branches</span>" +\n      \'<span class="gt-pill">\' + aheadTotal + " commits ahead of " + esc(data.base) + "</span>" +\n      \'<span class="gt-pill">\' + prs.length + " open PRs</span>" +\n    "</div>" +\n    \'<div class="gt-gen">Generated \' + esc(data.generated_at || "") +\n      \' &middot; regen: <code>.\\\\.venv\\\\Scripts\\\\python.exe scripts\\\\git_tree.py</code></div>\';\n  mount.appendChild(header);\n\n  // --- usage instructions ---\n  var howto = document.createElement("details");\n  howto.className = "gt-howto";\n  howto.open = true;\n  howto.innerHTML =\n    "<summary>How to use this page</summary>" +\n    \'<div class="gt-howto-body">\' +\n      "<p>This page is a static snapshot \\u2014 it does <strong>not</strong> update on its own. " +\n      "Re-run the script, then refresh the browser tab.</p>" +\n      "<ol>" +\n        "<li><strong>Regenerate the snapshot</strong> (from the repo root, Windows):<br>" +\n          "<code>.\\\\.venv\\\\Scripts\\\\python.exe scripts\\\\git_tree.py</code></li>" +\n        "<li><strong>Refresh this page</strong> in your browser: " +\n          "<kbd>F5</kbd> (or <kbd>Ctrl</kbd>+<kbd>R</kbd>; " +\n          "<kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>R</kbd> to hard-refresh).</li>" +\n      "</ol>" +\n      "<p class=\\"gt-howto-note\\">Options: <code>--fragment</code> prints the inner HTML for embedding in " +\n      "<code>tracker.html</code>; <code>-o &lt;path&gt;</code> writes to a custom file. " +\n      "PR badges require the <code>gh</code> CLI installed and authenticated.</p>" +\n    "</div>";\n  mount.appendChild(howto);\n\n  if (!data.prs || data.prs.available === false) {\n    var note = document.createElement("div");\n    note.className = "gt-ghnote";\n    note.textContent =\n      "PR data unavailable (gh CLI not installed or not authenticated) " +\n      "\\u2014 branch tree shown without PR badges.";\n    mount.appendChild(note);\n  }\n\n  // --- branch table ---\n  var table = document.createElement("table");\n  table.className = "gt-table";\n  table.innerHTML =\n    "<thead><tr><th>Branch</th><th>vs " + esc(data.base) +\n    "</th><th>Last commit</th><th>Age</th><th>Upstream</th><th>PR</th></tr></thead>";\n  var tbody = document.createElement("tbody");\n  branches.forEach(function (b) {\n    var tr = document.createElement("tr");\n    if (b.current) tr.className = "gt-row-cur";\n    var ahead = b.ahead || 0, behind = b.behind || 0;\n    var bars =\n      \'<span class="gt-ahead">\' + (ahead ? "+" + ahead : "") + "</span>" +\n      \'<span class="gt-behind">\' + (behind ? "\\u2212" + behind : "") + "</span>" +\n      (ahead === 0 && behind === 0 ? \'<span class="gt-even">in sync</span>\' : "");\n    var pr = prByHead[b.name];\n    var prCell = pr\n      ? \'<a class="gt-pr\' + (pr.isDraft ? " gt-pr-draft" : "") + \'" href="\' +\n        esc(pr.url) + \'" target="_blank" rel="noopener">#\' + esc(pr.number) +\n        (pr.isDraft ? " draft" : "") + "</a>"\n      : \'<span class="gt-dim">\\u2014</span>\';\n    tr.innerHTML =\n      "<td>" + (b.current ? "&#9733; " : "") + \'<span class="gt-bname">\' + esc(b.name) + "</span></td>" +\n      \'<td class="gt-vs">\' + bars + "</td>" +\n      \'<td class="gt-subj" title="\' + esc(b.subject) + \'"><code>\' + esc(b.sha) + "</code> " + esc(b.subject) + "</td>" +\n      "<td>" + esc(ago(b.date)) + "</td>" +\n      "<td>" + (\n        b.upstream\n          ? \'<span class="gt-dim">\' + esc(b.upstream) + "</span>"\n          : \'<span class="gt-warn">none</span>\'\n      ) + "</td>" +\n      "<td>" + prCell + "</td>";\n    tbody.appendChild(tr);\n  });\n  table.appendChild(tbody);\n  mount.appendChild(table);\n\n  // --- SVG commit graph (lane assignment) ---\n  var commits = data.commits || [];\n  var graphWrap = document.createElement("div");\n  graphWrap.className = "gt-graph-wrap";\n  if (commits.length) {\n    var lanes = [];\n    var pos = {};\n    function freeLane() {\n      var i = lanes.indexOf(null);\n      if (i === -1) { i = lanes.length; lanes.push(null); }\n      return i;\n    }\n    function dedupe() {\n      for (var a = 0; a < lanes.length; a++) {\n        if (lanes[a] === null) continue;\n        for (var b = a + 1; b < lanes.length; b++) {\n          if (lanes[b] === lanes[a]) lanes[b] = null;\n        }\n      }\n    }\n    var maxCol = 0;\n    commits.forEach(function (c, row) {\n      var col = lanes.indexOf(c.sha);\n      if (col === -1) { col = freeLane(); lanes[col] = c.sha; }\n      pos[c.sha] = { col: col, row: row };\n      if (col > maxCol) maxCol = col;\n      var parents = c.parents || [];\n      if (parents.length === 0) {\n        lanes[col] = null;\n      } else {\n        lanes[col] = parents[0];\n        for (var k = 1; k < parents.length; k++) {\n          if (lanes.indexOf(parents[k]) === -1) lanes[freeLane()] = parents[k];\n        }\n      }\n      dedupe();\n    });\n\n    var COLW = 18, ROWH = 30, PADX = 14, PADY = 18, R = 5;\n    var graphW = PADX * 2 + (maxCol + 1) * COLW;\n    var textX = graphW + 8;\n    var height = PADY * 2 + commits.length * ROWH;\n    function cx(col) { return PADX + col * COLW; }\n    function cy(row) { return PADY + row * ROWH; }\n\n    var svgNS = "http://www.w3.org/2000/svg";\n    var svg = document.createElementNS(svgNS, "svg");\n    svg.setAttribute("class", "gt-svg");\n    svg.setAttribute("height", height);\n    svg.setAttribute("width", "100%");\n    svg.setAttribute("role", "img");\n    svg.setAttribute("aria-label", "commit graph");\n\n    // edges first (under nodes)\n    commits.forEach(function (c) {\n      var p = pos[c.sha];\n      (c.parents || []).forEach(function (par) {\n        var pp = pos[par];\n        if (!pp) return;\n        var x1 = cx(p.col), y1 = cy(p.row), x2 = cx(pp.col), y2 = cy(pp.row);\n        var path = document.createElementNS(svgNS, "path");\n        var d;\n        if (x1 === x2) {\n          d = "M" + x1 + "," + y1 + " L" + x2 + "," + y2;\n        } else {\n          var my = (y1 + y2) / 2;\n          d = "M" + x1 + "," + y1 + " C" + x1 + "," + my + " " + x2 + "," + my + " " + x2 + "," + y2;\n        }\n        path.setAttribute("d", d);\n        path.setAttribute("class", "gt-edge");\n        path.setAttribute("stroke", PALETTE[pp.col % PALETTE.length]);\n        svg.appendChild(path);\n      });\n    });\n\n    // nodes + labels\n    commits.forEach(function (c) {\n      var p = pos[c.sha];\n      var color = PALETTE[p.col % PALETTE.length];\n      var circ = document.createElementNS(svgNS, "circle");\n      circ.setAttribute("cx", cx(p.col));\n      circ.setAttribute("cy", cy(p.row));\n      circ.setAttribute("r", R);\n      circ.setAttribute("fill", color);\n      circ.setAttribute("class", "gt-node");\n      svg.appendChild(circ);\n\n      var label = document.createElementNS(svgNS, "text");\n      label.setAttribute("x", textX);\n      label.setAttribute("y", cy(p.row) + 4);\n      label.setAttribute("class", "gt-svg-text");\n      var tspanSha = document.createElementNS(svgNS, "tspan");\n      tspanSha.setAttribute("class", "gt-svg-sha");\n      tspanSha.textContent = c.sha + " ";\n      label.appendChild(tspanSha);\n      (c.refs || []).forEach(function (r) {\n        var t = document.createElementNS(svgNS, "tspan");\n        t.setAttribute("class", "gt-svg-ref");\n        t.textContent = "(" + r + ") ";\n        label.appendChild(t);\n      });\n      var tspanSub = document.createElementNS(svgNS, "tspan");\n      tspanSub.textContent = c.subject;\n      label.appendChild(tspanSub);\n      svg.appendChild(label);\n    });\n\n    graphWrap.appendChild(svg);\n  } else {\n    graphWrap.innerHTML = \'<div class="gt-dim">No commits found.</div>\';\n  }\n  var graphHeading = document.createElement("h2");\n  graphHeading.className = "gt-h2";\n  graphHeading.textContent = "Commit graph (newest first, up to " + (data.max_commits || 0) + ")";\n  mount.appendChild(graphHeading);\n  mount.appendChild(graphWrap);\n\n  // --- text fallback ---\n  if (data.graph_text) {\n    var details = document.createElement("details");\n    details.className = "gt-fallback";\n    var summary = document.createElement("summary");\n    summary.textContent = "Text graph (git log --graph)";\n    details.appendChild(summary);\n    var pre = document.createElement("pre");\n    pre.textContent = data.graph_text;\n    details.appendChild(pre);\n    mount.appendChild(details);\n  }\n})();\n'


def render_fragment(snapshot):
    payload = json.dumps(snapshot, ensure_ascii=False).replace("</", "<\\/")
    return _FRAGMENT_TEMPLATE.replace("__SCRIPT__", _render_script()).replace("__DATA__", payload)


def render_html(snapshot):
    fragment = render_fragment(snapshot)
    return f"""<!DOCTYPE html>\n<html lang="en" data-theme="dark">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n<title>{html.escape(str(snapshot.get("repo", "repo")))} - git family tree</title>\n<style>\n:root {{\n  --bg: #0f172a; --bg-panel: #1e293b; --bg-elev: #334155;\n  --border: rgb(71 85 105); --border-subtle: rgb(51 65 85);\n  --text: #e2e8f0; --text-bright: #f8fafc; --text-mute: #94a3b8;\n  --accent: #38bdf8;\n}}\n* {{ box-sizing: border-box; }}\nbody {{\n  margin: 0; padding: 24px; background: var(--bg); color: var(--text);\n  font: 14px/1.5 -apple-system, "Segoe UI", system-ui, sans-serif;\n  color-scheme: dark;\n}}\ncode, pre {{ font-family: "JetBrains Mono", Consolas, ui-monospace, monospace; }}\n.git-tree {{ max-width: 1100px; margin: 0 auto; }}\n.gt-header {{\n  background: var(--bg-panel); border: 1px solid var(--border-subtle);\n  border-radius: 12px; padding: 16px 20px; margin-bottom: 18px;\n}}\n.gt-title {{ font-size: 20px; font-weight: 700; color: var(--text-bright); }}\n.gt-meta {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }}\n.gt-gen {{ margin-top: 10px; color: var(--text-mute); font-size: 12px; }}\n.gt-gen code {{ color: var(--accent); }}\n.gt-badge, .gt-pill {{\n  display: inline-block; padding: 2px 10px; border-radius: 999px;\n  font-size: 12px; font-weight: 600;\n}}\n.gt-pill {{ background: var(--bg-elev); color: var(--text-mute); }}\n.gt-badge-cur {{ background: color-mix(in srgb, var(--accent) 22%, transparent); color: var(--accent); }}\n.gt-badge-ok {{ background: rgba(52, 211, 153, 0.18); color: #34d399; }}\n.gt-badge-warn {{ background: rgba(251, 191, 36, 0.18); color: #fbbf24; }}\n.gt-ghnote {{\n  background: rgba(251, 191, 36, 0.1); border: 1px solid rgba(251, 191, 36, 0.3);\n  color: #fbbf24; border-radius: 8px; padding: 8px 12px; margin-bottom: 16px; font-size: 13px;\n}}\n.gt-howto {{\n  background: var(--bg-panel); border: 1px solid var(--border-subtle);\n  border-radius: 12px; padding: 4px 20px; margin-bottom: 18px;\n}}\n.gt-howto > summary {{\n  cursor: pointer; color: var(--text-bright); font-weight: 600;\n  padding: 12px 0; list-style: none;\n}}\n.gt-howto > summary::-webkit-details-marker {{ display: none; }}\n.gt-howto > summary::before {{ content: "\\25B8  "; color: var(--accent); }}\n.gt-howto[open] > summary::before {{ content: "\\25BE  "; }}\n.gt-howto-body {{ padding-bottom: 14px; color: var(--text); }}\n.gt-howto-body p {{ margin: 8px 0; }}\n.gt-howto-body ol {{ margin: 8px 0; padding-left: 22px; }}\n.gt-howto-body li {{ margin: 6px 0; }}\n.gt-howto-body code {{\n  background: #0b1120; border: 1px solid var(--border-subtle); border-radius: 6px;\n  padding: 1px 7px; color: var(--accent); font-size: 12.5px;\n}}\n.gt-howto-body kbd {{\n  background: var(--bg-elev); border: 1px solid var(--border); border-radius: 5px;\n  padding: 1px 6px; font-size: 12px; font-family: inherit; color: var(--text-bright);\n  box-shadow: 0 1px 0 var(--border);\n}}\n.gt-howto-note {{ color: var(--text-mute); font-size: 13px; }}\n.gt-table {{\n  width: 100%; border-collapse: collapse; margin-bottom: 26px;\n  background: var(--bg-panel); border-radius: 12px; overflow: hidden;\n}}\n.gt-table th, .gt-table td {{\n  text-align: left; padding: 9px 14px; border-bottom: 1px solid var(--border-subtle);\n  vertical-align: top;\n}}\n.gt-table th {{ color: var(--text-mute); font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }}\n.gt-table tr:last-child td {{ border-bottom: none; }}\n.gt-row-cur {{ background: color-mix(in srgb, var(--accent) 8%, transparent); }}\n.gt-bname {{ color: var(--text-bright); font-weight: 600; }}\n.gt-subj {{ max-width: 420px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}\n.gt-subj code {{ color: var(--accent); margin-right: 6px; }}\n.gt-ahead {{ color: #34d399; font-weight: 700; margin-right: 6px; }}\n.gt-behind {{ color: #fbbf24; font-weight: 700; }}\n.gt-even, .gt-dim {{ color: var(--text-mute); }}\n.gt-warn {{ color: #fbbf24; }}\n.gt-pr {{\n  display: inline-block; padding: 1px 8px; border-radius: 6px; text-decoration: none;\n  background: color-mix(in srgb, var(--accent) 18%, transparent); color: var(--accent); font-weight: 600;\n}}\n.gt-pr-draft {{ background: var(--bg-elev); color: var(--text-mute); }}\n.gt-h2 {{\n  font-size: 15px; color: var(--text-mute); text-transform: uppercase;\n  letter-spacing: .04em; margin: 0 0 8px;\n}}\n.gt-graph-wrap {{\n  background: var(--bg-panel); border: 1px solid var(--border-subtle);\n  border-radius: 12px; padding: 8px 4px; overflow-x: auto;\n}}\n.gt-svg {{ display: block; }}\n.gt-edge {{ fill: none; stroke-width: 2; opacity: 0.85; }}\n.gt-node {{ stroke: var(--bg-panel); stroke-width: 2; }}\n.gt-svg-text {{ fill: var(--text); font: 12px Consolas, ui-monospace, monospace; }}\n.gt-svg-sha {{ fill: var(--accent); }}\n.gt-svg-ref {{ fill: #fbbf24; font-weight: 700; }}\n.gt-fallback {{ margin-top: 18px; }}\n.gt-fallback summary {{ cursor: pointer; color: var(--text-mute); padding: 6px 0; }}\n.gt-fallback pre {{\n  background: #0b1120; border: 1px solid var(--border-subtle); border-radius: 8px;\n  padding: 12px; overflow-x: auto; font-size: 12px; color: var(--text-mute);\n}}\n</style>\n</head>\n<body>\n{fragment}\n</body>\n</html>\n"""


def main(argv=None):
    parser = argparse.ArgumentParser(description="Snapshot the git family tree to HTML.")
    parser.add_argument(
        "--fragment", action="store_true", help="Print only the inner HTML section (for embedding into tracker.html)."
    )
    parser.add_argument(
        "-o", "--output", default=None, help=f"Output path for the full page (default: {OUTPUT_NAME} at repo root)."
    )
    args = parser.parse_args(argv)
    snapshot = build_snapshot()
    if args.fragment:
        sys.stdout.write(render_fragment(snapshot))
        return 0
    out_path = Path(args.output) if args.output else ROOT / OUTPUT_NAME
    out_path.write_text(render_html(snapshot), encoding="utf-8")
    n_branches = len(snapshot["branches"])
    n_commits = len(snapshot["commits"])
    print(f"Wrote {out_path} ({n_branches} branches, {n_commits} commits).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
