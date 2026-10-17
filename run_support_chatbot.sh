#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

PORT="${STREAMLIT_PORT:-8501}"

exec uv run streamlit run support_chatbot.py \
  --server.headless true \
  --server.port "$PORT"
