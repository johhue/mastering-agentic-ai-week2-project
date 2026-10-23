#!/usr/bin/env bash
# Start project3 with the repository virtual environment from any directory.
set -euo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_PYTHON="$PROJECT_ROOT/.venv/bin/python"
if [[ ! -x "$PROJECT_PYTHON" ]]; then
  echo "ERROR: Project Python environment is missing. Run uv sync from $PROJECT_ROOT." >&2
  exit 1
fi
exec "$PROJECT_PYTHON" "$PROJECT_ROOT/project3/start_streamlit.py"
