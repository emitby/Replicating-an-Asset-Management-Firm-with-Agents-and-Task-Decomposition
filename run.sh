#!/usr/bin/env sh
# Launcher: keeps every library cache inside the project (CLAUDE.md guardrail), then runs the CLI.
#   ./run.sh run [--offline] | stage <name> --from runs/<id> | eval [--live] | render-pages runs/<id> | test
ROOT="$(cd "$(dirname "$0")" && pwd)"
export MPLCONFIGDIR="$ROOT/.cache/matplotlib"
export PYTHONPYCACHEPREFIX="$ROOT/.cache/pycache"
if [ -x "$ROOT/.venv/bin/python" ]; then PY="$ROOT/.venv/bin/python"; else PY="$ROOT/.venv/Scripts/python.exe"; fi
cd "$ROOT" || exit 1
if [ "$1" = "test" ]; then shift; exec "$PY" -m pytest "$@"; fi
exec "$PY" -m strategy "$@"
