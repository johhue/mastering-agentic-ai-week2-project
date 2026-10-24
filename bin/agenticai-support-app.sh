#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

PORT="${STREAMLIT_SUPPORT_APP_PORT:-8501}"

exec uv run streamlit run agenticai-support-app.py \
  --server.headless true \
  --server.port "$PORT"
