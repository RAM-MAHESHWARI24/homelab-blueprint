#!/usr/bin/env bash
# ==============================================================================
# noodle-gallery-tools - standalone install (outside the homelab-blueprint installer)
#
#   ./install.sh                 create .env and check tools; run the exporter by hand
#   sudo ./install.sh --cron     also install the ML schedule and nightly backup
#                                to /etc/cron.d (renders host/cron/* templates)
#
# Edit .env first: IMMICH_URL, IMMICH_API_KEY, the Postgres container name and
# the library path. Existing .env files are never overwritten.
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

WITH_CRON=false
case "${1:-}" in
    --cron) WITH_CRON=true ;;
    -h|--help) sed -n '2,11p' "$0"; exit 0 ;;
    "") ;;
    *) echo "Unknown option: $1 (try --help)" >&2; exit 2 ;;
esac

command -v python3 >/dev/null || { echo "python3 is required." >&2; exit 1; }
command -v exiftool >/dev/null || echo "Note: exiftool is not installed (apt install libimage-exiftool-perl); the exporter needs it."
command -v docker >/dev/null || echo "Note: docker CLI not found; the exporter reads faces from the Postgres container through it."

if [ ! -f .env ]; then
    cp .env.example .env
    chmod 600 .env
    echo "Created .env from .env.example. Fill in IMMICH_URL and IMMICH_API_KEY."
fi

if $WITH_CRON; then
    [ "$(id -u)" -eq 0 ] || { echo "--cron needs root (sudo)." >&2; exit 1; }
    set -a
    # shellcheck source=/dev/null
    . ./.env
    set +a
    BACKUP_DIR="${BACKUP_LOCAL:-/var/backups/immich}"
    STATE_DIR="$(dirname "$BACKUP_DIR")"
    mkdir -p "$BACKUP_DIR"
    install -m 0755 scripts/immich-ml-control.sh /usr/local/sbin/immich-ml-control.sh
    install -m 0755 scripts/immich_backup_gdrive.sh.example /usr/local/sbin/immich_backup_gdrive.sh
    install -m 0755 scripts/photo_restore_test.sh /usr/local/sbin/photo_restore_test.sh
    install -m 0644 host/systemd/photo-restore-test.service host/systemd/photo-restore-test.timer /etc/systemd/system/
    systemctl daemon-reload
    systemctl enable --now photo-restore-test.timer
    # The cron templates use the blueprint's placeholders; fill them for a standalone host.
    sed -e "s|{{INSTALL_DIR}}/apps/immich-face-xmp-exporter|$SCRIPT_DIR|g" \
        -e "s|{{STATE_DIR}}/photo-backups|$BACKUP_DIR|g" \
        -e "s|{{STATE_DIR}}|$STATE_DIR|g" \
        -e "s|{{MEMORIES_DIR}}|${MEDIA_PATH:-/mnt/hdd/Memories}|g" \
        -e "s|{{GDRIVE_REMOTE}}|${GDRIVE_REMOTE:-gdrive:}|g" \
        -e "s|{{KEEP_LOCAL_DUMPS}}|${KEEP_LOCAL_DUMPS:-3}|g" \
        -e "s|{{KEEP_DRIVE_DUMPS}}|${KEEP_DRIVE_DUMPS:-14}|g" \
        -e "s|{{KEEP_DRIVE_MONTHLY}}|${KEEP_DRIVE_MONTHLY:-12}|g" \
        host/cron/immich-backup > /etc/cron.d/immich-backup
    cp host/cron/immich-ml /etc/cron.d/immich-ml
    chmod 0644 /etc/cron.d/immich-backup /etc/cron.d/immich-ml
    echo "Installed /etc/cron.d/immich-ml (06:00 start, 10:00 stop) and /etc/cron.d/immich-backup (22:00)."
fi

cat <<'EOF'

Installed. Export face tags to XMP sidecars:
  python3 export_faces_to_xmp.py --help    (standard library only)
EOF
