#!/bin/bash
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "Usage: $0 SEALED_REPLAY DEPLOY_DIRECTORY" >&2
  exit 2
fi

here=$(cd -- "$(dirname -- "$0")" && pwd)
repo=$(cd -- "$here/../.." && pwd)
sealed=$1
output=$2/.vercel/output
if [ ! -s "$sealed" ] || [ -e "$output" ]; then
  echo 'Supply a nonempty sealed replay and a fresh deployment output directory.' >&2
  exit 2
fi

work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
cp -R "$repo/web/src" "$work/"
cp "$repo/web/"{index.html,check-gateway.cjs,package.json,package-lock.json,tsconfig*.json,vite.config.ts} "$work/"
if [ -d "${SOONY_WEB_NODE_MODULES:-$repo/web/node_modules}" ]; then
  dependencies=$(cd -- "${SOONY_WEB_NODE_MODULES:-$repo/web/node_modules}" && pwd)
  ln -s "$dependencies" "$work/node_modules"
else
  npm --prefix "$work" ci
fi
VITE_SOONY_HOSTED_REPLAY=1 npm --prefix "$work" run build

function_dir="$output/functions/control.func"
mkdir -p "$function_dir" "$output/static"
cp "$here/output-config.json" "$output/config.json"
cp "$here/function-config.json" "$function_dir/.vc-config.json"
cp "$here/control.cjs" "$function_dir/index.cjs"
cp "$here/"{accounts.cjs,demo-users.json,live.cjs} "$function_dir/"
cp "$here/login.html" "$function_dir/login.html"
cp "$work/dist/index.html" "$function_dir/app.html"
cp -R "$work/dist/assets" "$work/dist/brand" "$output/static/"
install -m 600 "$sealed" "$function_dir/replay.enc"
