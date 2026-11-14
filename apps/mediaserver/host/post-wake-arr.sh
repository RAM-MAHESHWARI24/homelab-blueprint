#!/usr/bin/env bash
# ==============================================================================
# Homelab Mediaserver - post-wake recovery hook
#
# Runs after the host resumes from suspend (installed by the blueprint into
# /etc/server-suspend.d/50-mediaserver.sh, executed by server-suspend.sh).
# Clears Prowlarr's indexer backoff timers and kicks Radarr/Sonarr health
# checks and RSS syncs so the pipeline catches up on anything missed overnight.
#
# Reads API keys from the module env file (default /etc/homelab/mediaserver.env);
# every step is best effort and never fails the caller.
# ==============================================================================
set -uo pipefail

ENV_FILE="${MEDIASERVER_ENV:-/etc/homelab/mediaserver.env}"
HOST="${MEDIASERVER_HOST:-127.0.0.1}"
LOG_FILE="${POST_WAKE_LOG:-/var/log/server-suspend.log}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S %Z')] [RECOVERY] $*" >> "$LOG_FILE" 2>/dev/null || true; }

if [ -r "$ENV_FILE" ]; then
    # shellcheck disable=SC1090
    set -a; . "$ENV_FILE"; set +a
fi

PROWLARR_API_KEY="${PROWLARR_API_KEY:-}"
RADARR_API_KEY="${RADARR_API_KEY:-}"
SONARR_API_KEY="${SONARR_API_KEY:-}"

if ! command -v curl >/dev/null 2>&1; then
    log "curl not installed; skipping media pipeline recovery."
    exit 0
fi

arr_command() { # <port> <api key> <command name>
    curl -s -m 15 -X POST "http://${HOST}:$1/api/v3/command" \
        -H "X-Api-Key: $2" -H "Content-Type: application/json" \
        -d "{\"name\":\"$3\"}" >/dev/null 2>&1 || true
}

if [ -n "$PROWLARR_API_KEY" ]; then
    log "Triggering Prowlarr indexer health recheck..."
    curl -s -m 15 -X POST "http://${HOST}:9696/api/v1/indexer/testall" \
        -H "X-Api-Key: $PROWLARR_API_KEY" >/dev/null 2>&1 || true
fi

if [ -n "$RADARR_API_KEY" ]; then
    log "Triggering Radarr health check and RSS sync..."
    arr_command 7878 "$RADARR_API_KEY" CheckHealth
    arr_command 7878 "$RADARR_API_KEY" RssSync
fi

if [ -n "$SONARR_API_KEY" ]; then
    log "Triggering Sonarr health check and RSS sync..."
    arr_command 8989 "$SONARR_API_KEY" CheckHealth
    arr_command 8989 "$SONARR_API_KEY" RssSync
fi

log "Post-wake media pipeline recovery completed."
exit 0
