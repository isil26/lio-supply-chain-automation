#!/bin/bash
set -euo pipefail
if [ "$#" -ne 1 ]; then
  echo 'Usage: package-live.sh FRESH_DEPLOY_DIRECTORY' >&2
  exit 2
fi
here=$(cd -- "$(dirname -- "$0")" && pwd)
gateway=${SOONY_GATEWAY_SOURCE:-$here}
output=$1/.vercel/output
if [ -e "$output" ]; then
  echo 'Use a fresh deployment directory.' >&2
  exit 2
fi
function_dir="$output/functions/control.func"
mkdir -p "$function_dir" "$output/static/brand"
output=$(cd "$output" && pwd)
cp "$here/../../web/src/desk/manti-logo.png" "$output/static/brand/"
cp "$gateway/control.cjs" "$function_dir/index.cjs"
cp "$gateway/"{accounts.cjs,demo-users.json,live.cjs} "$function_dir/"
cp "$gateway/function-config.json" "$function_dir/.vc-config.json"
cp "$here/login.html" "$function_dir/"
web="$here/../../web"
if [[ ! -x "$web/node_modules/.bin/vite" ]]; then
  npm --prefix "$web" ci --no-audit --no-fund
fi
npm --prefix "$web" run build:guest -- --outDir "$output/static/demo"
cat > "$output/config.json" <<'JSON'
{
  "version": 3,
  "routes": [
    { "src": "^/$", "dest": "/control?op=home" },
    { "src": "^/login$", "dest": "/control?op=login" },
    { "src": "^/logout$", "dest": "/control?op=logout" },
    { "src": "^/demo/(.*)$", "headers": { "Content-Security-Policy": "default-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'none'; form-action 'none'; frame-ancestors 'none'; base-uri 'none'" }, "continue": true },
    { "src": "^/(api/.*|assets/[A-Za-z0-9_.-]+|live|react|game-cards)$", "dest": "/control?live=/$1" },
    { "handle": "filesystem" }
  ]
}
JSON
