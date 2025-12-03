#!/usr/bin/env bash

LOG_FILE="$HOME/bobiverse/logs/orchestrator.log"

if [ ! -f "$LOG_FILE" ]; then
  echo "[tail-orch-logs] Log file not found: $LOG_FILE"
  exit 1
fi

echo "Tailing $LOG_FILE (Ctrl+C to stop)..."
tail -F "$LOG_FILE"
