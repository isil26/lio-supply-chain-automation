#!/bin/bash
set -euo pipefail
here=$(cd -- "$(dirname -- "$0")" && pwd)
if [[ $# != 1 ]]; then echo 'Usage: package-vm.sh FRESH_DEPLOY_DIRECTORY' >&2; exit 2; fi
revision=$(cat "$here/../backend/live-revision")
source_dir=$(mktemp -d)
trap 'rm -rf "$source_dir"' EXIT
git -C "$here/../.." archive "$revision" deploy/vercel | tar -x -C "$source_dir"
bash "$source_dir/deploy/vercel/package-live.sh" "$@"
function_dir="$1/.vercel/output/functions/control.func"
mv "$function_dir/index.cjs" "$function_dir/control.cjs"
sed '/<!-- NAMED_ACCOUNT_START -->/,/<!-- NAMED_ACCOUNT_END -->/d' "$source_dir/deploy/vercel/login.html" > "$function_dir/login.html"
cp "$here/vm-transport/entry.cjs" "$function_dir/index.cjs"
cp "$here/vm-transport/"package*.json "$function_dir/"
cp "$here/../backend/vm_known_hosts" "$function_dir/"
npm ci --prefix "$function_dir" --omit=optional --ignore-scripts --no-audit --no-fund
