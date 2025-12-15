#!/usr/bin/env bash
set -euo pipefail

cd /home/matt-mitchell/bobiverse

# Use the venv explicitly
PY="/home/matt-mitchell/bobiverse/.venv/bin/python"

# Start FastAPI app in package mode
exec "$PY" -m uvicorn orchestrator.main:app \
  --host 0.0.0.0 \
  --port "${ORCHESTRATOR_PORT:-5080}"
