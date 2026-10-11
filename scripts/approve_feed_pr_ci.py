#!/usr/bin/env python3
"""Approve the waiting pull_request CI run on the bot-owned feed refresh PR.

Pushes made with GITHUB_TOKEN leave the PR's CI run in ``action_required``, and
required checks only count from that PR run (a workflow_dispatch run on the same
SHA does not unblock the merge). Never fails the calling job: problems surface
as ``::warning::`` lines so the feed PR can be approved by hand.

``--dry-run`` only reports which run would be approved.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

DEFAULT_BRANCH = "chore/claims-feed-refresh"


def _gh(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=False)


def list_pr_runs(branch: str) -> list[dict]:
    proc = _gh(
        "run", "list", "--workflow", "ci.yml", "--branch", branch, "--event", "pull_request",
        "--limit", "10", "--json", "databaseId,headSha,status,conclusion,createdAt",
    )  # fmt: skip
    if proc.returncode != 0:
        print(f"::warning::gh run list failed: {proc.stderr.strip()}", flush=True)
        return []
    runs = json.loads(proc.stdout or "[]")
    return runs if isinstance(runs, list) else []


def select_waiting_run(runs: list[dict], head_sha: str) -> dict | None:
    """Newest run for ``head_sha`` that is still waiting for approval."""
    for run in runs:
        if run.get("headSha") == head_sha and run.get("conclusion") == "action_required":
            return run
    return None


def approve(repo: str, run_id: int) -> bool:
    proc = _gh("api", "-X", "POST", f"repos/{repo}/actions/runs/{run_id}/approve")
    if proc.returncode != 0:
        print(f"::warning::approve failed for run {run_id}: {proc.stderr.strip()}", flush=True)
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--branch", default=DEFAULT_BRANCH)
    parser.add_argument("--sha", help="Head SHA to approve (default: newest PR run's SHA)")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--wait-seconds", type=int, default=180)
    parser.add_argument("--interval", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if args.dry_run:
        runs = list_pr_runs(args.branch)
        if not runs:
            print(f"dry-run: no pull_request CI runs found on {args.branch}", flush=True)
            return 0
        sha = args.sha or runs[0].get("headSha", "")
        newest = runs[0]
        print(
            f"dry-run: newest PR run {newest.get('databaseId')} on {sha[:12]} is "
            f"{newest.get('status')}/{newest.get('conclusion') or '-'}",
            flush=True,
        )
        waiting = select_waiting_run(runs, sha)
        if waiting:
            print(f"dry-run: would approve run {waiting['databaseId']}", flush=True)
        else:
            print("dry-run: nothing waiting for approval on that SHA", flush=True)
        return 0

    if not args.sha or not args.repo:
        print("::warning::approve_feed_pr_ci needs --sha and --repo; skipping", flush=True)
        return 0

    deadline = time.monotonic() + args.wait_seconds
    while True:
        waiting = select_waiting_run(list_pr_runs(args.branch), args.sha)
        if waiting or time.monotonic() >= deadline:
            break
        time.sleep(args.interval)

    if not waiting:
        print(
            f"::warning::No action_required CI run found for {args.sha}; "
            "approve the feed PR's CI from the Actions tab if it is blocked.",
            flush=True,
        )
        return 0
    if approve(args.repo, int(waiting["databaseId"])):
        print(f"Approved CI run {waiting['databaseId']} for {args.sha[:12]}.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
