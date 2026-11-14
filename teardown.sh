#!/usr/bin/env bash
# ==============================================================================
# Homelab Blueprint - Teardown & Clean Uninstaller
#
# Removes exactly what the installer recorded in the install manifest
# (/var/lib/homelab/installed.json): compose stacks, systemd units, cron
# files, sudoers drop-ins, helper scripts and rendered env files. Media,
# photos and application databases are preserved unless --purge-data is given.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PURGE_DATA=false
NON_INTERACTIVE=false
DRY_RUN=false
MANIFEST_CLI="python3 $SCRIPT_DIR/setup/installer/manifest.py"
STATE_DIR="${HOMELAB_STATE_DIR:-/var/lib/homelab}"
ETC_DIR="${HOMELAB_ETC_DIR:-/etc/homelab}"
APPDATA_DIR="${HOMELAB_APPDATA_DIR:-/srv/homelab/appdata}"

usage() {
    cat <<EOF
Usage: sudo ./teardown.sh [OPTIONS]

Uninstalls Homelab Blueprint and stops all its services.

Options:
  -y, --yes, --force    Run non-interactively without confirmation prompts
  --purge-data          Also delete application configs/databases under $APPDATA_DIR
                        (media and photo libraries on your data disks are never touched)
  --dry-run             Show what would be removed without changing anything
  -h, --help            Show this help message and exit
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -y|--yes|--force) NON_INTERACTIVE=true; shift ;;
        --purge-data)     PURGE_DATA=true; shift ;;
        --dry-run)        DRY_RUN=true; shift ;;
        -h|--help)        usage ;;
        *) echo "Unknown option: $1 (see --help)"; exit 1 ;;
    esac
done

if [ "$EUID" -ne 0 ] && [ "$DRY_RUN" = false ]; then
    echo "Teardown needs root to stop services and remove system files. Re-launching with sudo..."
    exec sudo bash "$0" "$@"
fi

echo "============================================================"
echo "  Homelab Blueprint - Teardown"
echo "============================================================"
[ "$DRY_RUN" = true ] && echo "[DRY-RUN] Nothing will be modified."

log_action() {
    if [ "$DRY_RUN" = true ]; then echo "  [DRY-RUN] Would $1"; else echo "  - $1"; fi
}

# ------------------------------------------------------------------ manifest
HAVE_MANIFEST=false
if [ -f "$STATE_DIR/installed.json" ]; then
    HAVE_MANIFEST=true
    echo "Using install manifest: $STATE_DIR/installed.json"
else
    echo "No install manifest found; falling back to the known v1 layout."
fi

if [ "$NON_INTERACTIVE" = false ] && [ "$DRY_RUN" = false ]; then
    echo ""
    echo "This will:"
    echo "  1. Stop and remove the Docker Compose stacks (docker compose down)."
    echo "  2. Stop, disable and remove control-hub.service and other units."
    echo "  3. Remove cron jobs from /etc/cron.d/, sudoers drop-ins and helper scripts."
    echo "  4. Remove rendered configuration in $ETC_DIR."
    if [ "$PURGE_DATA" = true ]; then
        echo "  5. PERMANENTLY DELETE application configs and databases in $APPDATA_DIR."
    else
        echo "  5. Preserve all media, photos, configs and databases."
    fi
    echo ""
    read -rp "Proceed? [y/N]: " confirm
    [[ "$confirm" =~ ^[yY]([eE][sS])?$ ]] || { echo "Aborted. Nothing was changed."; exit 0; }
fi

# ------------------------------------------------------------ 1. compose down
echo ""
echo "[1/5] Stopping Docker Compose stacks..."
if command -v docker >/dev/null 2>&1; then
    if [ "$HAVE_MANIFEST" = true ]; then
        while IFS=$'\t' read -r module dir env_file; do
            [ -z "$dir" ] && continue
            if [ -f "$dir/docker-compose.yml" ]; then
                if [ "$DRY_RUN" = true ]; then
                    log_action "run 'docker compose down --remove-orphans' for $module in $dir"
                else
                    echo "  - $module: docker compose down"
                    (cd "$dir" && docker compose --env-file "$env_file" down --remove-orphans 2>/dev/null) || \
                    (cd "$dir" && docker compose down --remove-orphans 2>/dev/null) || true
                fi
            fi
        done < <($MANIFEST_CLI list compose 2>/dev/null || true)
    else
        for dir in "$SCRIPT_DIR/apps/mediaserver" "$SCRIPT_DIR/apps/noodle-gallery"; do
            [ -f "$dir/docker-compose.yml" ] || continue
            if [ "$DRY_RUN" = true ]; then
                log_action "run 'docker compose down --remove-orphans' in $dir"
            else
                (cd "$dir" && docker compose down --remove-orphans 2>/dev/null) || true
            fi
        done
    fi
fi

# ------------------------------------------------------------- 2. systemd
echo ""
echo "[2/5] Stopping systemd units..."
UNITS=()
if [ "$HAVE_MANIFEST" = true ]; then
    mapfile -t UNITS < <($MANIFEST_CLI list units 2>/dev/null || true)
fi
[ ${#UNITS[@]} -eq 0 ] && UNITS=("control-hub.service")
UNITS+=("homelab-netplan-revert.timer" "server-suspend-override.timer")

if command -v systemctl >/dev/null 2>&1; then
    for unit in "${UNITS[@]}"; do
        if [ "$DRY_RUN" = true ]; then
            log_action "stop, disable and remove $unit"
            continue
        fi
        systemctl stop "$unit" 2>/dev/null || true
        systemctl disable "$unit" 2>/dev/null || true
        if [ -f "/etc/systemd/system/$unit" ]; then
            rm -f "/etc/systemd/system/$unit"
            log_action "removed /etc/systemd/system/$unit"
        fi
    done
    [ "$DRY_RUN" = true ] || systemctl daemon-reload || true
fi

# ------------------------------------------------- 3. files, cron, sudoers
echo ""
echo "[3/5] Removing installed files (cron, sudoers, helpers, env files)..."
FILES=()
if [ "$HAVE_MANIFEST" = true ]; then
    mapfile -t FILES < <($MANIFEST_CLI list files 2>/dev/null || true)
else
    FILES=(
        /etc/cron.d/server-suspend /etc/cron.d/immich-backup /etc/cron.d/immich-ml
        /etc/cron.d/tv-updater /etc/cron.d/tv-autoupdater /etc/cron.d/watchtower
        /usr/local/sbin/server-suspend.sh /usr/local/sbin/immich-ml-control.sh
        /usr/local/sbin/watchtower-run.sh /usr/local/sbin/homelab-netplan-revert.sh
        /etc/sudoers.d/homelab-blueprint
    )
fi
FILES+=(/run/server-suspend.skip /run/server-suspend.override /usr/local/sbin/homelab-netplan-revert.sh)

for f in "${FILES[@]}"; do
    [ -z "$f" ] && continue
    # Safety: never delete anything outside the directories the installer writes to.
    case "$f" in
        /etc/cron.d/*|/etc/sudoers.d/*|/etc/systemd/system/*|/usr/local/sbin/*|/run/*|"$ETC_DIR"/*|"$STATE_DIR"/*|/etc/server-suspend.conf|/etc/sysctl.d/99-homelab-*) ;;
        *) echo "  ! skipping unexpected path from manifest: $f"; continue ;;
    esac
    if [ -e "$f" ] || [ -L "$f" ]; then
        if [ "$DRY_RUN" = true ]; then log_action "remove $f"; else rm -f "$f"; log_action "removed $f"; fi
    fi
done

# Module .env symlinks pointing into $ETC_DIR, the venv and dry-run previews live in the checkout
for link in "$SCRIPT_DIR"/apps/*/.env "$SCRIPT_DIR/.env" "$SCRIPT_DIR"/apps/*/config.json; do
    if [ -L "$link" ]; then
        if [ "$DRY_RUN" = true ]; then log_action "remove symlink $link"; else rm -f "$link"; fi
    fi
done
if [ -d "$SCRIPT_DIR/apps/control-hub/venv" ]; then
    if [ "$DRY_RUN" = true ]; then log_action "remove apps/control-hub/venv"; else rm -rf "$SCRIPT_DIR/apps/control-hub/venv"; log_action "removed apps/control-hub/venv"; fi
fi
if [ -d "$SCRIPT_DIR/setup/dry_run_preview" ]; then
    if [ "$DRY_RUN" = true ]; then log_action "remove setup/dry_run_preview"; else rm -rf "$SCRIPT_DIR/setup/dry_run_preview"; fi
fi

# ------------------------------------------------------- 4. etc + state dirs
echo ""
echo "[4/5] Removing rendered configuration and state..."
for d in "$ETC_DIR" "$STATE_DIR"; do
    if [ -d "$d" ]; then
        if [ "$DRY_RUN" = true ]; then log_action "remove directory $d"; else rm -rf "$d"; log_action "removed $d"; fi
    fi
done
if id -u homelab >/dev/null 2>&1; then
    if [ "$DRY_RUN" = true ]; then log_action "remove system user 'homelab'"; else userdel homelab 2>/dev/null || true; log_action "removed system user 'homelab'"; fi
fi

# ------------------------------------------------------------- 5. app data
echo ""
echo "[5/5] Application data..."
if [ "$PURGE_DATA" = true ]; then
    for target in "$APPDATA_DIR" "$SCRIPT_DIR/apps/mediaserver/config" "$SCRIPT_DIR/apps/noodle-gallery/data"; do
        [ -d "$target" ] || continue
        if [ "$DRY_RUN" = true ]; then log_action "purge $target"; else rm -rf "$target"; log_action "purged $target"; fi
    done
    echo "  Note: media and photo libraries on your data disks were left intact."
else
    echo "  Preserved: media, photos, container configs and databases."
fi

echo ""
echo "============================================================"
if [ "$DRY_RUN" = true ]; then
    echo "  [DRY-RUN] Teardown simulation complete. No changes made."
else
    echo "  Homelab Blueprint uninstalled."
fi
echo "============================================================"
