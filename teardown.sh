#!/usr/bin/env bash
# ==============================================================================
# Homelab Blueprint - Cluster Teardown & Clean Uninstaller
# Safely stops all containers, removes systemd daemons, clears cron jobs,
# and restores host state with optional data directory preservation.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Defaults
PURGE_DATA=false
NON_INTERACTIVE=false
DRY_RUN=false

usage() {
    cat <<EOF
Usage: sudo ./teardown.sh [OPTIONS]

Safely uninstalls Homelab Blueprint and stops all cluster workloads.

Options:
  -y, --yes, --force    Run non-interactively without confirmation prompts
  --purge-data          Permanently delete media, configs, and database directories
  --dry-run             Simulate teardown actions without modifying host or containers
  -h, --help            Show this help message and exit

Default Behavior:
  Stops and removes Docker containers, disables systemd services, removes cron
  jobs, but PRESERVES all your media files, photos, and persistent databases.
EOF
    exit 0
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        -y|--yes|--force)
            NON_INTERACTIVE=true
            shift
            ;;
        --purge-data)
            PURGE_DATA=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo "❌ Unknown option: $1"
            echo "   Run './teardown.sh --help' for usage."
            exit 1
            ;;
    esac
done

# Ensure running with root/sudo (unless running dry-run)
if [ "$EUID" -ne 0 ] && [ "$DRY_RUN" = false ]; then
    echo "⚠️ Cluster teardown requires root privileges to stop systemd daemons and remove cron jobs."
    echo "   Re-launching with sudo..."
    exec sudo bash "$0" "$@"
fi

echo "============================================================"
echo "  🧹 Homelab Blueprint - Teardown & Cluster Uninstaller"
echo "============================================================"

if [ "$DRY_RUN" = true ]; then
    echo "🔍 [DRY-RUN] Simulation mode active. No services or files will be modified."
fi

# Confirmation prompt for interactive runs
if [ "$NON_INTERACTIVE" = false ] && [ "$DRY_RUN" = false ]; then
    echo "This operation will:"
    echo "  1. Stop and remove all Media and Photo Docker containers."
    echo "  2. Stop and disable the Control Hub systemd daemon."
    echo "  3. Remove Homelab cron jobs from /etc/cron.d/."
    echo "  4. Remove helper binaries from /usr/local/sbin/."
    if [ "$PURGE_DATA" = true ]; then
        echo "  ⚠️ [PURGE] PERMANENTLY REMOVE all data, photos, configs, and databases!"
    else
        echo "  ✓ PRESERVE all media, photos, and configurations."
    fi
    echo ""
    read -rp "Are you sure you want to proceed? [y/N]: " confirm
    if [[ ! "$confirm" =~ ^[yY]([eE][sS])?$ ]]; then
        echo "Teardown aborted by user. Nothing was changed."
        exit 0
    fi
fi

log_action() {
    local action="$1"
    if [ "$DRY_RUN" = true ]; then
        echo "  [DRY-RUN] Would $action"
    else
        echo "  ✓ $action"
    fi
}

# 1. Stop and tear down Docker Compose stacks
echo ""
echo "🛑 [1/5] Stopping Docker Compose stacks..."

COMPOSE_DIRS=(
    "apps/mediaserver"
    "apps/noodle-gallery"
)

for dir in "${COMPOSE_DIRS[@]}"; do
    target_path="$SCRIPT_DIR/$dir"
    if [ -f "$target_path/docker-compose.yml" ] || [ -f "$target_path/docker-compose.yaml" ]; then
        if command -v docker &>/dev/null; then
            if [ "$DRY_RUN" = true ]; then
                log_action "run 'docker compose down --remove-orphans' in $dir"
            else
                echo "  -> Stopping stack in $dir..."
                (cd "$target_path" && docker compose down --remove-orphans 2>/dev/null || true)
            fi
        fi
    fi
done

# 2. Stop and disable Systemd Daemons
echo ""
echo "🛑 [2/5] Stopping systemd background daemons..."

if [ "$DRY_RUN" = true ]; then
    log_action "stop and disable control-hub.service"
    log_action "remove /etc/systemd/system/control-hub.service"
else
    if command -v systemctl &>/dev/null; then
        if systemctl is-active --quiet control-hub.service 2>/dev/null; then
            echo "  -> Stopping control-hub.service..."
            systemctl stop control-hub.service || true
        fi
        if systemctl is-enabled --quiet control-hub.service 2>/dev/null; then
            echo "  -> Disabling control-hub.service..."
            systemctl disable control-hub.service || true
        fi
        if [ -f "/etc/systemd/system/control-hub.service" ]; then
            rm -f "/etc/systemd/system/control-hub.service"
            systemctl daemon-reload || true
            log_action "Removed /etc/systemd/system/control-hub.service"
        fi
    fi
fi

# 3. Clean Cron Automation Jobs
echo ""
echo "⏰ [3/5] Cleaning cron automation entries..."

CRON_FILES=(
    "/etc/cron.d/server-suspend"
    "/etc/cron.d/immich-backup"
    "/etc/cron.d/immich-ml"
    "/etc/cron.d/tv-updater"
    "/etc/cron.d/watchtower"
)

for cron_file in "${CRON_FILES[@]}"; do
    if [ -f "$cron_file" ]; then
        if [ "$DRY_RUN" = true ]; then
            log_action "remove cron job $cron_file"
        else
            rm -f "$cron_file"
            log_action "Removed $cron_file"
        fi
    fi
done

# 4. Remove Host Helper Binaries & Sysctl/Sudoers Drops
echo ""
echo "🔧 [4/5] Removing host helper binaries & system integrations..."

SYSTEM_DROPS=(
    "/usr/local/sbin/server-suspend.sh"
    "/usr/local/sbin/immich-ml-control.sh"
    "/usr/local/sbin/watchtower-run.sh"
    "/etc/sysctl.d/99-tailscale.conf"
    "/etc/sudoers.d/homelab-blueprint"
    "/run/server-suspend.skip"
    "/run/server-suspend.override"
)

for drop in "${SYSTEM_DROPS[@]}"; do
    if [ -f "$drop" ]; then
        if [ "$DRY_RUN" = true ]; then
            log_action "remove $drop"
        else
            rm -f "$drop"
            log_action "Removed $drop"
        fi
    fi
done

# Clean Python virtual environment inside apps/control-hub
if [ -d "$SCRIPT_DIR/apps/control-hub/venv" ]; then
    if [ "$DRY_RUN" = true ]; then
        log_action "remove virtualenv at apps/control-hub/venv"
    else
        rm -rf "$SCRIPT_DIR/apps/control-hub/venv"
        log_action "Removed apps/control-hub/venv"
    fi
fi

# Clean setup preview folder if exists
if [ -d "$SCRIPT_DIR/setup/dry_run_preview" ]; then
    if [ "$DRY_RUN" = true ]; then
        log_action "clean preview folder at setup/dry_run_preview"
    else
        rm -rf "$SCRIPT_DIR/setup/dry_run_preview"
        log_action "Cleaned setup/dry_run_preview"
    fi
fi

# 5. Data Directory Handling
echo ""
echo "💾 [5/5] Storage & Data State..."

if [ "$PURGE_DATA" = true ]; then
    echo "  ⚠️ PURGE MODE ENABLED: Cleaning configuration directories..."
    PURGE_TARGETS=(
        "$SCRIPT_DIR/apps/mediaserver/config"
        "$SCRIPT_DIR/apps/noodle-gallery/data"
    )
    for target in "${PURGE_TARGETS[@]}"; do
        if [ -d "$target" ]; then
            if [ "$DRY_RUN" = true ]; then
                log_action "purge directory $target"
            else
                rm -rf "$target"
                log_action "Purged $target"
            fi
        fi
    done
    echo "  ℹ️ Note: External media paths (e.g. /mnt/hdd/data) were left intact for data safety."
else
    echo "  ✓ Media, Photos, and SQLite/Postgres databases PRESERVED safely on disk."
fi

echo ""
echo "============================================================"
if [ "$DRY_RUN" = true ]; then
    echo "  ✨ [DRY-RUN] Teardown simulation complete. No changes made."
else
    echo "  ✅ Homelab Blueprint successfully uninstalled."
    echo "  Your host system is clean and all background services stopped."
fi
echo "============================================================"
