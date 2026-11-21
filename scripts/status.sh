#!/bin/sh
# One-screen team status: board, inbox, recent commits.
cd "$(dirname "$0")/.." || exit 1
echo "=== STATUS ==="; cat coord/STATUS.md
echo; echo "=== OPEN INBOX ==="; grep -v 'DONE' coord/INBOX.md | tail -n +2
echo; echo "=== RECENT COMMITS ==="; git log --all --oneline -n 15 2>/dev/null
echo; echo "=== DATA CHANGES ==="; tail -n 10 bridge/changes.log 2>/dev/null
echo
echo "=== LLM COST ==="
python3 scripts/cost_report.py
