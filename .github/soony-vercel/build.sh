#!/usr/bin/env bash
set -euo pipefail
umask 077

repo=$(git rev-parse --show-toplevel)
release=$1
ci="$repo/.github/soony-vercel"
# 19:25 portal snapshot (4de57a7): compare the tree, including paths and contents.
snapshot_tree=31ad7fb407298bf83c021f4976bc30e96f5176ca
if [[ "$(git rev-parse HEAD:case-data)" != "$snapshot_tree" ]]; then
  echo "::error::case-data differs from the approved 19:25 snapshot. Verify and authorize the new snapshot before changing the pin."
  exit 1
fi

mkdir -m 700 "$release"
source_dir="$release/source"
mkdir -p "$source_dir/deploy" "$source_dir/docs"
cp -R "$repo/"{bridge,src,web,config} "$source_dir/"
cp -R "$repo/docs/agent_runs" "$source_dir/docs/"
cp -R "$repo/deploy/vercel" "$source_dir/deploy/"
python "$ci/fixtures.py" stage "$source_dir" "$ci"

key=$(mktemp)
trap 'rm -f "$key"' EXIT
if [[ "${PUBLISH:-false}" == true ]]; then
  test -n "${SOONY_REPLAY_KEY:-}"
  printf '%s' "$SOONY_REPLAY_KEY" > "$key"
else
  openssl rand -hex 32 > "$key"
fi
unset SOONY_REPLAY_KEY SOONY_MAIL_HISTORY_DB
SOONY_LLM_PROVIDER=none SOONY_AGENTS=0 CHASER_REAL_SMTP=0 CHASER_AUTO_SEND=0 OMP_THREAD_LIMIT=1 \
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$source_dir" \
  python "$source_dir/deploy/vercel/prepare_replay.py" "$repo/case-data" 2>"$release/replay-build.log" |
  node "$source_dir/deploy/vercel/seal_replay.cjs" "$key" "$release/replay.enc" || {
    echo "::error::The deterministic replay build failed before packaging."
    exit 1
  }
"$source_dir/deploy/vercel/package.sh" "$release/replay.enc" "$release/deployment"
python "$ci/fixtures.py" audit "$repo" "$release/deployment/.vercel/output"
