#!/bin/bash
# One-command launcher for the Siglent SDM web app.
#
# Creates .venv on first run, installs requirements, then launches the
# chromeless browser window via launch.py. Idempotent: re-running is fine.
#
# macOS users: a symlink "run.command" points at this same file so it
# can be opened by double-click from Finder.
set -euo pipefail

cd "$(cd "$(dirname "$0")" && pwd)"

PY="${PY:-python3}"
VENV=".venv"

if [ ! -d "$VENV" ]; then
  echo "[run] creating $VENV ..."
  "$PY" -m venv "$VENV"
fi

# shellcheck disable=SC1091
source "$VENV/bin/activate"

# Install / refresh deps quietly. requirements.txt is the source of truth.
# Skip if the lock-equivalent (requirements.txt mtime) hasn't changed since
# the venv was last touched.
STAMP="$VENV/.deps-stamp"
if [ ! -f "$STAMP" ] || [ requirements.txt -nt "$STAMP" ]; then
  echo "[run] installing dependencies ..."
  pip install --upgrade pip --quiet
  pip install -r requirements.txt --quiet
  touch "$STAMP"
fi

# Pass through any args (e.g. --lan)
exec "$VENV/bin/python" launch.py "$@"
