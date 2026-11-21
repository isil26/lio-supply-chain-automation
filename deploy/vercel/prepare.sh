#!/bin/bash
set -euo pipefail

if [ "$#" -ne 3 ]; then
  echo "Usage: $0 SNAPSHOT_DIR ENCRYPTION_KEY_FILE SEALED_OUTPUT" >&2
  exit 2
fi

here=$(cd -- "$(dirname -- "$0")" && pwd)
repo=$(cd -- "$here/../.." && pwd)
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
cp -R "$repo/src" "$work/"
mkdir "$work/bridge"
cp "$repo/bridge/live.py" "$repo/bridge/sync.py" "$work/bridge/"

PYTHONPATH="$work" PYTHONDONTWRITEBYTECODE=1 SOONY_LLM_PROVIDER=none SOONY_AGENTS=0 CHASER_REAL_SMTP=0 OMP_THREAD_LIMIT=1 \
  "${SOONY_BUILD_PYTHON:-python3}" "$here/prepare_replay.py" "$1" |
  node "$here/seal_replay.cjs" "$2" "$work/replay.enc"
install -m 600 "$work/replay.enc" "$3"
