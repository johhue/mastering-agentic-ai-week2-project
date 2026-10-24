#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

PORT="${STREAMLIT_SUPPORT_APP_PORT:-5566}"

exec uv run streamlit run agenticai-comparison-app.py \
  --server.headless true \
  --server.port "$PORT"
