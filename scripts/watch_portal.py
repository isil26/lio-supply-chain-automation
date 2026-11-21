#!/usr/bin/env python3
"""T50 portal watcher: notice unannounced Soony drops and tell the team.

Every cycle (default 10 min):
  1. run bridge/sync.py (needs the team token in SOONY_TOKEN or .soony_token),
  2. if files are new, changed or removed: rebuild a private snapshot store and
     compare the STD/CE forecast and component gaps with the previous cycle,
  3. append one line to coord/INBOX.md and push it (only that file is committed).

The first run seeds data/ and bridge/state.json from the committed case-data/
snapshot, so only real drops after that snapshot are reported.

Usage:
  python scripts/watch_portal.py            # loop every 10 min
  python scripts/watch_portal.py --cycle    # one cycle, then exit
  python scripts/watch_portal.py --no-push  # report locally only
Raw files stay in the gitignored data/ folder; no token or file content is written to git.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA, SNAPSHOT = ROOT / "data", ROOT / "case-data"
STATE = ROOT / "bridge" / "state.json"
DB = ROOT / "store" / "watch.db"
LAST = ROOT / "store" / "watch_last.json"
INBOX = ROOT / "coord" / "INBOX.md"
NAME = "isil-agent (T50 watcher)"
TO = "nick, copilot-live, ALL"
CHANGE = re.compile(r"^(NEW|CHANGED|REMOVED) (.+)$")


def log(message):
    print(f"[{datetime.now():%H:%M:%S}] {message}", flush=True)


def has_token():
    return bool(os.environ.get("SOONY_TOKEN") or (ROOT / ".soony_token").is_file())


def seed():
    """Start from the committed snapshot so only later drops count as changes."""
    if STATE.exists():
        return False
    state = {}
    for path in sorted(p for p in SNAPSHOT.rglob("*") if p.is_file()):
        rel = path.relative_to(SNAPSHOT).as_posix()
        target = DATA / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copy2(path, target)
        state[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    STATE.write_text(json.dumps(state, indent=1), encoding="utf-8")
    log(f"seeded {len(state)} files from case-data/")
    return True


def sync():
    result = subprocess.run([sys.executable, str(ROOT / "bridge" / "sync.py")], cwd=ROOT,
                            capture_output=True, text=True, encoding="utf-8", timeout=600)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip().splitlines()[-1][:200])
    return [m.groups() for m in map(CHANGE.match, result.stdout.splitlines()) if m]


def forecast():
    """Evaluate data/ in a private store; return p50 per edition and component gaps."""
    env = dict(os.environ, PYTHONUTF8="1", CHASER_REAL_SMTP="0", CHASER_AUTO_SEND="0", SOONY_LLM_PROVIDER="none")
    result = subprocess.run([sys.executable, "-m", "src.orchestrator", "--once", "--data", str(DATA), "--db", str(DB)],
                            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", env=env, timeout=1200)
    if result.returncode:
        raise RuntimeError((result.stderr or "forecast failed").strip().splitlines()[-1][:200])
    board = json.loads(result.stdout)
    return {
        "editions": {row["edition"]: row["p50"] for row in board.get("readiness", [])},
        "gaps": {row["id"]: row.get("gap", 0) for row in board.get("risks", [])},
        "health": board.get("dataHealth", {}),
    }


def describe(changes, before, after):
    kinds = {k: [p for kind, p in changes if kind == k] for k in ("NEW", "CHANGED", "REMOVED")}
    files = "; ".join(f"{k.lower()}: " + ", ".join(Path(p).name for p in ps[:4]) + (f" +{len(ps) - 4}" if len(ps) > 4 else "")
                      for k, ps in kinds.items() if ps)
    parts = [f"Portal drop, {len(changes)} file(s) ({files})."]
    if after:
        editions = ", ".join(f"{e} {before['editions'].get(e, '?'):,} -> {v:,}" if before and isinstance(before["editions"].get(e), int)
                             else f"{e} {v:,}" for e, v in after["editions"].items())
        parts.append(f"Forecast p50: {editions}.")
        if before:
            moved = [f"{part} {before['gaps'].get(part, 0):,} -> {gap:,}" for part, gap in after["gaps"].items()
                     if before["gaps"].get(part, 0) != gap]
            moved += [f"{part} {gap:,} -> 0" for part, gap in before["gaps"].items() if part not in after["gaps"] and gap]
            parts.append("Gaps changed: " + "; ".join(moved) + "." if moved else "No component gap changed.")
        health, earlier = after.get("health") or {}, (before or {}).get("health") or {}
        if health.get("errors") or health.get("needsReview", 0) > earlier.get("needsReview", 0):
            parts.append(f"Data health: {health.get('errors', 0)} errors, {health.get('needsReview', 0)} need review.")
    parts.append("Files are in data/ via `python bridge/sync.py` (team token); refresh your store before demoing.")
    return " ".join(parts)


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")


def post(line, push):
    text = INBOX.read_text(encoding="utf-8")
    nl = "\r\n" if "\r\n" in text else "\n"
    INBOX.write_text(text.rstrip("\r\n") + nl + line + nl, encoding="utf-8", newline="")
    if not push:
        return log("posted locally (no push)")
    git("add", str(INBOX.relative_to(ROOT)))
    git("-c", "user.name=isil-agent", "commit", "-q", "-m", f"T50: portal drop reported [isil-agent]")
    for _ in range(5):
        if git("pull", "-q", "--rebase", "--autostash", "origin", "main").returncode == 0 and \
                git("push", "-q", "origin", "HEAD:main").returncode == 0:
            return log("posted and pushed")
        git("rebase", "--abort")
        time.sleep(5)
    log("push failed; the line is committed locally")


def cycle(push):
    seed()
    if not has_token():
        return log("no team token (.soony_token or SOONY_TOKEN); skipping this cycle")
    changes = sync()
    if not changes:
        return log("no portal changes")
    log(f"{len(changes)} change(s): " + ", ".join(p for _, p in changes[:6]))
    before = json.loads(LAST.read_text(encoding="utf-8")) if LAST.exists() else None
    try:
        after = forecast()
        LAST.parent.mkdir(exist_ok=True)
        LAST.write_text(json.dumps(after), encoding="utf-8")
    except (RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        after = None
        log(f"forecast refresh failed: {exc}")
    post(f"[{datetime.now():%d %b %H:%M}] {NAME} -> {TO}: {describe(changes, before, after)}", push)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cycle", action="store_true", help="run one cycle and exit")
    parser.add_argument("--no-push", action="store_true", help="append to INBOX locally without committing")
    parser.add_argument("--interval", type=int, default=600, help="seconds between cycles (default 600)")
    parser.add_argument("--baseline", action="store_true", help="compute the forecast for the current data/ and exit")
    args = parser.parse_args()
    if args.baseline:
        seed()
        LAST.parent.mkdir(exist_ok=True)
        LAST.write_text(json.dumps(forecast()), encoding="utf-8")
        return log("baseline forecast saved")
    while True:
        try:
            cycle(push=not args.no_push)
        except Exception as exc:  # keep watching after a network or portal error
            log(f"cycle failed: {exc.__class__.__name__}: {exc}")
        if args.cycle:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
