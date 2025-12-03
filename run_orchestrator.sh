#!/usr/bin/env bash
set -e

# Move into orchestrator folder
cd /home/matt-mitchell/bobiverse/orchestrator

# Activate virtualenv
source /home/matt-mitchell/bobiverse/.venv/bin/activate

# Run orchestrator (this is what you already do manually)
exec python main.py
