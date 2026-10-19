#!/usr/bin/env bash
# Runs everything that must pass before a change counts as done:
# the backend tests, then the dashboard build.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"

echo "== Backend tests"
cd "$root/backend"
if [ -x .venv/bin/python ]; then py=.venv/bin/python; else py=python3; fi
"$py" -m pytest -q

echo "== Dashboard build"
cd "$root/dashboard"
[ -d node_modules ] || npm ci
npm run build

echo "All checks passed."
