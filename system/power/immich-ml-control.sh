#!/bin/bash
ACTION="${1:-status}"
LOG_FILE="/var/log/immich-ml.log"
touch "$LOG_FILE"
chmod 644 "$LOG_FILE"
TS=$(date '+%Y-%m-%d %H:%M:%S %Z')

case "$ACTION" in
    start)
        echo "[$TS] [START] Starting container 'immich_machine_learning'..." >> "$LOG_FILE"
        if docker start immich_machine_learning >> "$LOG_FILE" 2>&1; then
            echo "[$TS] [START] Container started successfully." >> "$LOG_FILE"
        else
            echo "[$TS] [ERROR] Failed to start container!" >> "$LOG_FILE"
        fi
        ;;
    stop)
        echo "[$TS] [STOP] Stopping container 'immich_machine_learning' to conserve RAM/CPU..." >> "$LOG_FILE"
        if docker stop immich_machine_learning >> "$LOG_FILE" 2>&1; then
            echo "[$TS] [STOP] Container stopped successfully." >> "$LOG_FILE"
        else
            echo "[$TS] [ERROR] Failed to stop container!" >> "$LOG_FILE"
        fi
        ;;
    *)
        echo "Usage: $0 {start|stop}"
        exit 1
        ;;
esac
