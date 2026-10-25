#!/usr/bin/env bash
# Watchtower Morning Container Update Runner
# Executes one-shot Docker container updates, writes daily physical logs,
# and retains the last 7 days of logs.

set -euo pipefail

LOG_DIR="/var/log/watchtower"
DATE=$(date +'%Y-%m-%d')
mkdir -p "$LOG_DIR"
chmod 755 "$LOG_DIR"

LOG_FILE="$LOG_DIR/watchtower_${DATE}.log"

{
  echo "=========================================================="
  echo "Watchtower Update Check Started: $(date '+%Y-%m-%d %H:%M:%S %Z')"
  echo "=========================================================="
} >> "$LOG_FILE"

# Run Watchtower in one-shot mode with explicit DNS resolvers and image cleanup
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  --dns 8.8.8.8 --dns 1.1.1.1 \
  -e TZ=Asia/Kolkata \
  containrrr/watchtower:latest \
  --run-once \
  --cleanup >> "$LOG_FILE" 2>&1 || true

{
  echo "=========================================================="
  echo "Watchtower Update Check Finished: $(date '+%Y-%m-%d %H:%M:%S %Z')"
  echo "=========================================================="
} >> "$LOG_FILE"

# Enforce 7-day log retention policy (remove daily logs older than 7 days)
find "$LOG_DIR" -name "watchtower_*.log" -type f -mtime +7 -delete
