#!/usr/bin/env bash
set -e

# Root of the bobiverse
cd /home/matt/bobiverse

# Activate venv
source /home/matt/bobiverse/.venv/bin/activate

# --- Start Dev Council ---
cd /home/matt/bobiverse/councils/dev_council

# Avoid duplicate processes if script is run twice
if ! pgrep -f "dev_council_service.py" > /dev/null; then
  nohup python dev_council_service.py \
    >> /home/matt/bobiverse/logs/dev_council.log 2>&1 &
fi

# --- Start Node Agent ---
cd /home/matt/bobiverse/node_agent

if ! pgrep -f "node_agent/main.py" > /dev/null && ! pgrep -f "python main.py" > /dev/null; then
  nohup python main.py \
    >> /home/matt/bobiverse/logs/node_agent.log 2>&1 &
fi
