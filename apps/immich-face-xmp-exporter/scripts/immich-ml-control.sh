#!/usr/bin/env bash
# ==============================================================================
# Noodle Gallery / Immich ML Power & Resource Throttler
# Schedules starting/stopping the machine-learning container to conserve
# CPU and RAM during peak human activity or off-peak hours on low-power servers.
# ==============================================================================

ACTION="${1:-status}"
CONTAINER_NAME="${IMMICH_ML_CONTAINER:-immich_machine_learning}"
LOG_FILE="${ML_LOG_FILE:-/var/log/immich-ml.log}"

touch "$LOG_FILE" 2>/dev/null || LOG_FILE="/tmp/immich-ml.log"
TS=$(date '+%Y-%m-%d %H:%M:%S %Z')

case "$ACTION" in
    start)
        echo "[$TS] [START] Starting machine learning container '$CONTAINER_NAME'..." >> "$LOG_FILE"
        if docker start "$CONTAINER_NAME" >> "$LOG_FILE" 2>&1; then
            echo "[$TS] [START] Container started successfully." >> "$LOG_FILE"
        else
            echo "[$TS] [ERROR] Failed to start container '$CONTAINER_NAME'!" >> "$LOG_FILE"
        fi
        ;;
    stop)
        echo "[$TS] [STOP] Stopping machine learning container '$CONTAINER_NAME' to conserve RAM/CPU..." >> "$LOG_FILE"
        if docker stop "$CONTAINER_NAME" >> "$LOG_FILE" 2>&1; then
            echo "[$TS] [STOP] Container stopped successfully." >> "$LOG_FILE"
        else
            echo "[$TS] [ERROR] Failed to stop container '$CONTAINER_NAME'!" >> "$LOG_FILE"
        fi
        ;;
    status)
        docker ps --filter "name=$CONTAINER_NAME" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
        ;;
    *)
        echo "Usage: $0 {start|stop|status}"
        exit 1
        ;;
esac
