#!/usr/bin/env bash
set -euo pipefail

# Create runtime directories if they don't exist (e.g. on first volume mount)
mkdir -p /app/output
mkdir -p /app/logs

# Execute the main application
exec python main.py "$@"
