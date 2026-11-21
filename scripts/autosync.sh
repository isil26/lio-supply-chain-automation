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
  if ! git pull --rebase --autostash -q origin main >/dev/null 2>&1; then
    # coord/*.md are append-only logs: on conflict keep both sides and continue (up to 20 rounds)
    n=0
    while [ -n "$(git diff --name-only --diff-filter=U)" ] && [ $n -lt 20 ]; do
      n=$((n+1))
      other=$(git diff --name-only --diff-filter=U | grep -v '^coord/.*\.md$')
      if [ -n "$other" ]; then echo "$ts CONFLICT outside coord/: $other"; git rebase --abort 2>/dev/null; break; fi
      for f in $(git diff --name-only --diff-filter=U); do
        sed -i '' -e '/^<<<<<<< /d' -e '/^=======$/d' -e '/^>>>>>>> /d' -e '/^||||||| /d' "$f"; git add "$f"
      done
      GIT_EDITOR=true git -c user.name=nick -c user.email="federspiel.nick@gmail.com" rebase --continue >/dev/null 2>&1
    done
    git stash list | grep -q autostash && git stash drop -q 2>/dev/null
  fi
  if git status -sb | head -1 | grep -q "no branch"; then
    echo "$ts rebase still in progress, resolve by hand"
  else
    git push -q origin main 2>&1 | tail -1
    echo "$ts in sync at $(git rev-parse --short HEAD)"
  fi
  sleep "$INTERVAL"
done
