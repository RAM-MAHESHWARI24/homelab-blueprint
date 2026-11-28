#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# Monthly restore test of the photo database backup.
#
# Proves that the newest dump on the remote can actually be restored:
#   1. download the newest immich_db_YYYYMMDD_HHMMSS.sql.gz from the remote
#      (not the local copy: the remote copy is what a restore would use)
#   2. check the gzip stream
#   3. load it into a throwaway Postgres container (same image as the live
#      database, no network, 1 GB memory cap, random password, temp folder)
#   4. count the photos and videos in the restored database and compare with the
#      rows of the asset table in the dump file itself
#   5. remove the container and every temporary file, always
#
# The result goes into status.json ("restore_test"), which the Control Hub shows
# on the backup card and alerts on. Runs from photo-restore-test.timer (first
# Sunday of the month, 11:00) or "Run restore test now" in the Control Hub.
# Settings: the same environment / /etc/cron.d/immich-backup lines as the backup.
# ==============================================================================

BACKUP_CRON_FILE="${BACKUP_CRON_FILE:-/etc/cron.d/immich-backup}"
if [ -r "$BACKUP_CRON_FILE" ]; then
    while IFS='=' read -r key value; do
        case "$key" in
            BACKUP_LOCAL|GDRIVE_REMOTE|FACE_EXPORTER|DB_CONTAINER|BACKUP_HELPER)
                if [ -z "${!key:-}" ]; then
                    printf -v "$key" '%s' "$value"
                    export "${key?}"
                fi
                ;;
        esac
    done < "$BACKUP_CRON_FILE"
fi
BACKUP_LOCAL="${BACKUP_LOCAL:-/var/lib/homelab/photo-backups}"
GDRIVE_REMOTE="${GDRIVE_REMOTE:-gdrive:}"
case "$GDRIVE_REMOTE" in *:|*/) ;; *) GDRIVE_REMOTE="${GDRIVE_REMOTE}/" ;; esac
FACE_EXPORTER="${FACE_EXPORTER:-$(dirname "$0")/../export_faces_to_xmp.py}"
DB_CONTAINER="${DB_CONTAINER:-immich_postgres}"
BACKUP_HELPER="${BACKUP_HELPER:-$(dirname "$FACE_EXPORTER")/scripts/backup_status.py}"
GDRIVE_DB_BACKUP="${GDRIVE_REMOTE}Immich_Backup/database"
STATUS_FILE="$BACKUP_LOCAL/status.json"
WORK="$BACKUP_LOCAL/.restore-test"
NAME="photo-restore-test"
RESTORE_DB="${RESTORE_DB:-immich}"

mkdir -p "$BACKUP_LOCAL"
# Never at the same time as a backup run (they share the dump folder and the remote).
exec 9>"$BACKUP_LOCAL/.backup.lock"
if ! flock -n 9; then
    echo "A backup is running; the restore test will run next time." >&2
    exit 0
fi
exec > >(tee -a "$BACKUP_LOCAL/restore-test.log") 2>&1

STARTED_AT="$(date -Is)"
DUMP=""
EXPECTED=""
RESTORED=""
DONE=0
FAIL_MSG=""

record() {
    # record <ok|fail> <message>
    [ -f "$BACKUP_HELPER" ] || { echo "Warning: $BACKUP_HELPER not found; result not recorded."; return 0; }
    python3 "$BACKUP_HELPER" restore-result --file "$STATUS_FILE" --result "$1" --message "$2" \
        --started-at "$STARTED_AT" --completed-at "$(date -Is)" --dump-file "$DUMP" \
        --expected "$EXPECTED" --restored "$RESTORED" || echo "Warning: could not write $STATUS_FILE"
}

fail() {
    FAIL_MSG="$1"
    echo "ERROR: $1"
    exit 1
}

cleanup() {
    local rc=$?
    docker rm -f "$NAME" >/dev/null 2>&1 || true
    rm -rf "$WORK"
    if [ "$DONE" -eq 0 ]; then
        record fail "${FAIL_MSG:-Restore test stopped unexpectedly (exit $rc)}"
    fi
}
trap cleanup EXIT

echo "=================================================="
echo "Starting photo database restore test: $(date)"
echo "=================================================="
docker rm -f "$NAME" >/dev/null 2>&1 || true
rm -rf "$WORK"
mkdir -p "$WORK"
chmod 700 "$WORK"

# 1. Newest dump on the remote
DUMP="$(timeout 300 rclone lsf --files-only "$GDRIVE_DB_BACKUP/" 2>/dev/null \
    | grep -E '^immich_db_[0-9]{8}_[0-9]{6}\.sql\.gz$' | sort | tail -n 1 || true)"
[ -n "$DUMP" ] || fail "No database dump found on $GDRIVE_DB_BACKUP (or the remote did not answer)."
echo "[1/5] Downloading $DUMP from $GDRIVE_DB_BACKUP..."
timeout 3600 rclone copy "$GDRIVE_DB_BACKUP/$DUMP" "$WORK/" || fail "Could not download $DUMP from the remote."

# 2. Integrity of the compressed stream
echo "[2/5] Checking the gzip stream..."
gzip -t "$WORK/$DUMP" || fail "$DUMP on the remote is damaged (gzip test failed)."

# What the dump itself contains: rows of the asset table that are not deleted.
if [ -f "$BACKUP_HELPER" ]; then
    EXPECTED="$(python3 "$BACKUP_HELPER" count-assets "$WORK/$DUMP" 2>/dev/null || true)"
fi

# 3. Throwaway database with the live image
IMAGE="$(docker inspect -f '{{.Config.Image}}' "$DB_CONTAINER" 2>/dev/null || true)"
[ -n "$IMAGE" ] || fail "Could not read the image of $DB_CONTAINER (is the photo database running?)."
echo "[3/5] Starting a throwaway database ($IMAGE)..."
PASSWORD="$(head -c 32 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 24)"
mkdir -p "$WORK/pgdata"
docker run -d --name "$NAME" --network none --memory 1g --cpus 2 --shm-size 128m \
    -e POSTGRES_PASSWORD="$PASSWORD" -e POSTGRES_USER=postgres -e POSTGRES_INITDB_ARGS=--data-checksums \
    -v "$WORK/pgdata:/var/lib/postgresql/data" "$IMAGE" >/dev/null \
    || fail "Could not start the throwaway database container."
ready=0
for _ in $(seq 1 90); do
    if docker logs "$NAME" 2>&1 | grep -q "PostgreSQL init process complete" \
        && docker exec "$NAME" pg_isready -U postgres -q 2>/dev/null; then
        ready=1
        break
    fi
    sleep 2
done
[ "$ready" -eq 1 ] || fail "The throwaway database did not start within 3 minutes."

# 4. Restore and count
echo "[4/5] Restoring $DUMP (this takes a few minutes)..."
gunzip -c "$WORK/$DUMP" | docker exec -i "$NAME" psql -U postgres -d postgres -q -o /dev/null 2> "$WORK/restore.err" || true
# pg_dumpall recreates the postgres role, which already exists: that error is expected.
ERRORS="$(grep -c 'ERROR:' "$WORK/restore.err" || true)"
UNEXPECTED="$(grep 'ERROR:' "$WORK/restore.err" | grep -vc 'role "postgres" already exists' || true)"
RESTORED="$(docker exec "$NAME" psql -U postgres -d "$RESTORE_DB" -t -A \
    -c 'SELECT count(*) FROM asset WHERE "deletedAt" IS NULL' 2>/dev/null | tr -d '[:space:]' || true)"
echo "[5/5] Restored photos and videos: ${RESTORED:-none}; expected: ${EXPECTED:-not recorded}; psql errors: $ERRORS ($UNEXPECTED unexpected)"
if [ "$UNEXPECTED" -gt 0 ]; then
    grep 'ERROR:' "$WORK/restore.err" | grep -v 'role "postgres" already exists' | head -5
fi

case "$RESTORED" in ''|*[!0-9]*) fail "The restored database has no readable asset table (psql errors: $UNEXPECTED)." ;; esac
[ "$RESTORED" -gt 0 ] || fail "The restored database contains no photos."
if [ -n "$EXPECTED" ] && [ "$RESTORED" -ne "$EXPECTED" ]; then
    fail "Restored $RESTORED photos and videos, but the dump contains $EXPECTED."
fi

DONE=1
if [ -n "$EXPECTED" ]; then
    record ok "Restored $DUMP: all $RESTORED photos and videos in the dump came back."
else
    record ok "Restored $DUMP: $RESTORED photos and videos (the dump could not be counted to compare)."
fi
echo "Restore test passed: $(date)"
