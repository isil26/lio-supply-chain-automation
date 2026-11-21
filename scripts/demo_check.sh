#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
exec python3 -m unittest discover -s tests -p test_e2e.py -v
