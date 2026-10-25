#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# Homelab Dynamic Suspend to RAM (S3) & Post-Wake Self-Healing Routine
# ==============================================================================

LOG_FILE="${SERVER_SUSPEND_LOG:-/var/log/server-suspend.log}"
SKIP_FILE="${SERVER_SUSPEND_SKIP:-/run/server-suspend.skip}"
OVERRIDE_FILE="${SERVER_SUSPEND_OVERRIDE:-/run/server-suspend.override}"
CONFIG_FILE="${SERVER_SUSPEND_CONF:-/etc/server-suspend.conf}"

# Touch log if directory is accessible
mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true
touch "$LOG_FILE" 2>/dev/null || true
chmod 644 "$LOG_FILE" 2>/dev/null || true

ts() {
    date '+%Y-%m-%d %H:%M:%S %Z'
}

echo "------------------------------------------------------------" >> "$LOG_FILE"
echo "[$(ts)] [TRIGGER] Server suspend check triggered (args: $*)." >> "$LOG_FILE"

# 1. Skip Flag Check
if [ -e "$SKIP_FILE" ]; then
    echo "[$(ts)] [SKIP] Found skip flag at '$SKIP_FILE'." >> "$LOG_FILE"
    echo "[$(ts)] [SKIP] Server sleep aborted for tonight. Clearing skip flag and overrides..." >> "$LOG_FILE"
    rm -f "$SKIP_FILE"
    rm -f "$OVERRIDE_FILE"
    echo "[$(ts)] [SKIP] Flags cleared successfully. Server will remain active." >> "$LOG_FILE"
    exit 0
fi

# 2. Check for Tonight's Override Deferral (unless invoked with --override or --force)
IS_OVERRIDE_RUN=false
IS_DRY_RUN=false
for arg in "$@"; do
    if [[ "$arg" == "--override" || "$arg" == "--force" ]]; then
        IS_OVERRIDE_RUN=true
    elif [[ "$arg" == "--dry-run" ]]; then
        IS_DRY_RUN=true
    fi
done

if [[ "${DRY_RUN:-0}" == "1" ]]; then
    IS_DRY_RUN=true
fi

if [ "$IS_OVERRIDE_RUN" = false ] && [ -f "$OVERRIDE_FILE" ]; then
    OVERRIDE_ACTIVE=$(jq -r '.active // empty' "$OVERRIDE_FILE" 2>/dev/null || echo "")
    OVERRIDE_TIME=$(jq -r '.sleep_time // empty' "$OVERRIDE_FILE" 2>/dev/null || echo "")
    CURRENT_TIME=$(date '+%H:%M')

    if [[ "$OVERRIDE_ACTIVE" == "true" && -n "$OVERRIDE_TIME" && "$OVERRIDE_TIME" != "$CURRENT_TIME" ]]; then
        echo "[$(ts)] [OVERRIDE-DEFER] Sleep is overridden for tonight to execute at $OVERRIDE_TIME (currently $CURRENT_TIME). Deferring standard schedule." >> "$LOG_FILE"
        exit 0
    fi
fi

# 3. Dynamic Safety: Defer midnight suspend if backup or sync is in progress
if pgrep -f "immich_backup_gdrive.sh" >/dev/null 2>&1 || pgrep -f "rclone sync" >/dev/null 2>&1 || pgrep -f "pg_dumpall" >/dev/null 2>&1; then
    echo "[$(ts)] [DEFER] Cloud backup or database dump is currently in progress. Skipping suspend." >> "$LOG_FILE"
    exit 0
fi

# 4. Calculate Sleep Duration (Seconds)
SLEEP_DURATION=21600 # Default fallback: 6 hours (21600 seconds)

if [ -f "$OVERRIDE_FILE" ]; then
    O_DUR=$(jq -r '.duration_seconds // empty' "$OVERRIDE_FILE" 2>/dev/null || echo "")
    if [[ -n "$O_DUR" && "$O_DUR" -gt 0 ]]; then
        SLEEP_DURATION=$O_DUR
        echo "[$(ts)] [OVERRIDE] Using tonight's override sleep duration: ${SLEEP_DURATION}s." >> "$LOG_FILE"
    fi
elif [ -f "$CONFIG_FILE" ]; then
    C_DUR=$(jq -r '.duration_seconds // empty' "$CONFIG_FILE" 2>/dev/null || echo "")
    if [[ -n "$C_DUR" && "$C_DUR" -gt 0 ]]; then
        SLEEP_DURATION=$C_DUR
        echo "[$(ts)] [CONFIG] Using configured permanent sleep duration: ${SLEEP_DURATION}s." >> "$LOG_FILE"
    fi
fi

HOURS_FLOAT=$(awk "BEGIN {printf \"%.1f\", $SLEEP_DURATION/3600}")
echo "[$(ts)] [SUSPEND] Preparing to suspend system to RAM (S3) for ${HOURS_FLOAT} hours (${SLEEP_DURATION}s)..." >> "$LOG_FILE"

if [ "$IS_DRY_RUN" = true ]; then
    echo "[$(ts)] [DRY_RUN] Dry run enabled. Skipping actual rtcwake execution." >> "$LOG_FILE"
else
    echo "[$(ts)] [SUSPEND] Invoking '/usr/sbin/rtcwake -m mem -s ${SLEEP_DURATION}'..." >> "$LOG_FILE"
    # Run rtcwake and log output
    if /usr/sbin/rtcwake -m mem -s "$SLEEP_DURATION" >> "$LOG_FILE" 2>&1; then
        echo "[$(ts)] [RESUME] rtcwake completed successfully. System has resumed from sleep." >> "$LOG_FILE"
    else
        EXIT_CODE=$?
        echo "[$(ts)] [ERROR] rtcwake failed with exit code $EXIT_CODE!" >> "$LOG_FILE"
        exit $EXIT_CODE
    fi
fi

# Clear tonight's override upon waking up
if [ -f "$OVERRIDE_FILE" ]; then
    rm -f "$OVERRIDE_FILE"
    echo "[$(ts)] [CLEANUP] Tonight's sleep override file cleared. Schedule reverted to default." >> "$LOG_FILE"
fi

# ==============================================================================
# Post-Resume Self-Healing: Network Verification & Media Pipeline Recovery
# ==============================================================================
echo "[$(ts)] [RESUME] Waiting up to 30s for network connectivity to stabilize..." >> "$LOG_FILE"
NET_READY=false
for i in {1..15}; do
    if ping -c 1 -W 2 1.1.1.1 >/dev/null 2>&1 || ping -c 1 -W 2 8.8.8.8 >/dev/null 2>&1; then
        echo "[$(ts)] [RESUME] Network connectivity verified online after ${i} check(s)." >> "$LOG_FILE"
        NET_READY=true
        break
    fi
    sleep 2
done

if [ "$NET_READY" = false ]; then
    echo "[$(ts)] [WARNING] Network did not respond to ping within 30s. Continuing recovery anyway." >> "$LOG_FILE"
fi

# Brief delay to allow background daemons to bind sockets
sleep 5

# Load API keys from environment or config file if present
PROWLARR_API_KEY="${PROWLARR_API_KEY:-YOUR_PROWLARR_API_KEY}"
RADARR_API_KEY="${RADARR_API_KEY:-YOUR_RADARR_API_KEY}"
SONARR_API_KEY="${SONARR_API_KEY:-YOUR_SONARR_API_KEY}"

# Recheck and revive Prowlarr indexers (clears backoff penalty timers)
if [ "$PROWLARR_API_KEY" != "YOUR_PROWLARR_API_KEY" ]; then
    echo "[$(ts)] [RECOVERY] Triggering Prowlarr indexer health recheck..." >> "$LOG_FILE"
    curl -s -X POST "http://localhost:9696/api/v1/indexer/testall" \
        -H "X-Api-Key: $PROWLARR_API_KEY" >/dev/null 2>&1 || true
fi

# Trigger Radarr health check & RSS sync
if [ "$RADARR_API_KEY" != "YOUR_RADARR_API_KEY" ]; then
    echo "[$(ts)] [RECOVERY] Triggering Radarr health check and RSS sync..." >> "$LOG_FILE"
    curl -s -X POST "http://localhost:7878/api/v3/command" \
        -H "X-Api-Key: $RADARR_API_KEY" \
        -H "Content-Type: application/json" \
        -d '{"name":"CheckHealth"}' >/dev/null 2>&1 || true
    curl -s -X POST "http://localhost:7878/api/v3/command" \
        -H "X-Api-Key: $RADARR_API_KEY" \
        -H "Content-Type: application/json" \
        -d '{"name":"RssSync"}' >/dev/null 2>&1 || true
fi

# Trigger Sonarr health check & RSS sync
if [ "$SONARR_API_KEY" != "YOUR_SONARR_API_KEY" ]; then
    echo "[$(ts)] [RECOVERY] Triggering Sonarr health check and RSS sync..." >> "$LOG_FILE"
    curl -s -X POST "http://localhost:8989/api/v3/command" \
        -H "X-Api-Key: $SONARR_API_KEY" \
        -H "Content-Type: application/json" \
        -d '{"name":"CheckHealth"}' >/dev/null 2>&1 || true
    curl -s -X POST "http://localhost:8989/api/v3/command" \
        -H "X-Api-Key: $SONARR_API_KEY" \
        -H "Content-Type: application/json" \
        -d '{"name":"RssSync"}' >/dev/null 2>&1 || true
fi

echo "[$(ts)] [RECOVERY] Post-wake media pipeline recovery completed successfully." >> "$LOG_FILE"
