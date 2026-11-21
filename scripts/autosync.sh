#!/bin/sh
# Constant stream: every INTERVAL seconds commit all work in the shared tree and push to origin/main.
# Safety: python must compile, no token/data/store in the index, aborts (and logs) on rebase conflicts.
# Usage: ./scripts/autosync.sh [interval_seconds]   (default 180). Stop with Ctrl+C or `hc kill autosync`.
cd "$(dirname "$0")/.." || exit 1
INTERVAL="${1:-180}"
PY=python3; [ -x .venv/bin/python ] && PY=.venv/bin/python
while true; do
  ts=$(date +%H:%M:%S)
  git add -A
  if ! git diff --cached --quiet; then
    if git diff --cached --name-only | grep -qE '(^|/)(\.soony_token|\.env)$|^data/|^store/|node_modules/'; then
      echo "$ts BLOCKED: sensitive path staged"; git reset -q
    elif ! $PY -m compileall -q src >/dev/null 2>&1; then
      echo "$ts SKIP: python does not compile, will retry"; git reset -q
    else
      files=$(git diff --cached --name-only | wc -l | tr -d ' ')
      git -c user.name=nick -c user.email="federspiel.nick@gmail.com" commit -qm "autosync: $files files [nick]

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>" && echo "$ts committed $files files"
    fi
  fi
  if git pull --rebase --autostash -q origin main 2>/dev/null; then
    git push -q origin main 2>&1 | tail -1
    echo "$ts in sync at $(git rev-parse --short HEAD)"
  else
    echo "$ts CONFLICT during rebase, aborted; resolve by hand (git status)"; git rebase --abort 2>/dev/null
  fi
  sleep "$INTERVAL"
done
