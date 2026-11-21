#!/usr/bin/env bash
# Checks for the standalone noodle-gallery-tools repo. Run by its own CI workflow, and
# by the homelab-blueprint split-simulation job against an isolated copy of this folder.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

echo "== compile and CLI parsing (stdlib only)"
python3 -m py_compile export_faces_to_xmp.py sync_space_faces.py scripts/backup_status.py
python3 scripts/backup_status.py --help >/dev/null
python3 export_faces_to_xmp.py --help >/dev/null
python3 sync_space_faces.py --help >/dev/null

echo "== unit tests"
python3 -m unittest tests.test_unit tests.test_backup_status

if command -v shellcheck >/dev/null; then
    echo "== shellcheck"
    shellcheck --severity=warning install.sh ci.sh scripts/immich-ml-control.sh scripts/immich_backup_gdrive.sh.example scripts/photo_restore_test.sh
else
    echo "(shellcheck not installed, skipped)"
fi
echo "noodle-gallery-tools checks passed"
