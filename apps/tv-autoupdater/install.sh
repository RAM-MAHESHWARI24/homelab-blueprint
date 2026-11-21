#!/usr/bin/env bash
# ==============================================================================
# tv-autoupdater - standalone install (outside the homelab-blueprint installer)
#
#   ./install.sh            create config.json from the example and check adb
#   ./install.sh --cron     also schedule it every 15 minutes, 06:00-23:45,
#                           in the current user's crontab (setup_cron.sh)
#
# Edit config.json first: your TVs' addresses. APKs are only installed when
# their signing certificate matches the SHA-256 pinned in config.json.
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
command -v adb >/dev/null || echo "Note: adb is not installed (apt install android-tools-adb); it is needed to reach the TVs."

python3 -m pip install -q --user -r requirements.txt 2>/dev/null \
    || echo "Note: install the requirements yourself (pip install -r requirements.txt) if pip refuses here."

if [ ! -f config.json ]; then
    cp config.example.json config.json
    echo "Created config.json. Add your TVs' IP addresses to it."
fi
mkdir -p incoming_apks

if $WITH_CRON; then
    ./setup_cron.sh
fi

cat <<'EOF'

Installed. Check what it would do:
  python3 tv_updater.py --help
EOF
