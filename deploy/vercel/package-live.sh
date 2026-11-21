#!/bin/bash
set -euo pipefail
if [ "$#" -ne 1 ]; then
  echo 'Usage: package-live.sh FRESH_DEPLOY_DIRECTORY' >&2
  exit 2
fi
here=$(cd -- "$(dirname -- "$0")" && pwd)
output=$1/.vercel/output
if [ -e "$output" ]; then
  echo 'Use a fresh deployment directory.' >&2
  exit 2
fi
function_dir="$output/functions/control.func"
mkdir -p "$function_dir"
cp "$here/control.cjs" "$function_dir/index.cjs"
cp "$here/"{login.html,live.cjs} "$function_dir/"
cp "$here/function-config.json" "$function_dir/.vc-config.json"
cat > "$output/config.json" <<'JSON'
{
  "version": 3,
  "routes": [
    { "src": "^/$", "dest": "/control?op=home" },
    { "src": "^/login$", "dest": "/control?op=login" },
    { "src": "^/logout$", "dest": "/control?op=logout" },
    { "src": "^/(api/.*|assets/[A-Za-z0-9_.-]+|live|react)$", "dest": "/control?live=/$1" },
    { "handle": "filesystem" }
  ]
}
JSON
