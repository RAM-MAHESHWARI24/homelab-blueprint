#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Run every 15 minutes between 06:00 and 23:59 (server waking hours)
CRON_CMD="*/15 6-23 * * * /usr/bin/python3 $SCRIPT_DIR/tv_updater.py >> /var/log/tv-updater.log 2>&1"

(crontab -l 2>/dev/null | grep -v "tv_updater.py" || true; echo "$CRON_CMD") | crontab -

echo "Crontab successfully updated:"
crontab -l
