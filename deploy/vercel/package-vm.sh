#!/bin/bash
set -euo pipefail
here=$(cd -- "$(dirname -- "$0")" && pwd)
bash "$here/package-live.sh" "$@"
function_dir="$1/.vercel/output/functions/control.func"
mv "$function_dir/index.cjs" "$function_dir/control.cjs"
cp "$here/vm-transport/entry.cjs" "$function_dir/index.cjs"
cp "$here/vm-transport/"package*.json "$function_dir/"
cp "$here/../backend/vm_known_hosts" "$function_dir/"
npm ci --prefix "$function_dir" --omit=optional --ignore-scripts --no-audit --no-fund
