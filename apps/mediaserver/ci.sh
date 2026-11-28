#!/usr/bin/env bash
# Checks for the standalone homelab-mediaserver repo. Run by its own CI workflow, and
# by the homelab-blueprint split-simulation job against an isolated copy of this folder.
# The full install-and-wire test lives in the blueprint's real-install CI job.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

echo "== python scripts (stdlib only)"
python3 -m py_compile scripts/*.py
python3 scripts/wire_arr.py --help >/dev/null
python3 scripts/wire_arr.py seed --help >/dev/null
python3 scripts/wire_arr.py profiles --help >/dev/null
python3 scripts/trash_sync.py --help >/dev/null
python3 scripts/media_config_backup.py --help >/dev/null
python3 scripts/auto_import.py --help >/dev/null
python3 scripts/download_doctor.py --help >/dev/null

echo "== unit tests"
python3 -m unittest discover -s tests

echo "== pinned images"
if grep -nE 'image:.*:(latest|release|main|develop)\s*$' docker-compose.yml; then
    echo "floating image tag found" >&2
    exit 1
fi

if command -v shellcheck >/dev/null; then
    echo "== shellcheck"
    shellcheck --severity=warning install.sh ci.sh host/post-wake-arr.sh
else
    echo "(shellcheck not installed, skipped)"
fi

if command -v docker >/dev/null && docker compose version >/dev/null 2>&1; then
    echo "== compose config"
    docker compose --env-file .env.example config --quiet
    docker compose --env-file .env.example -f docker-compose.yml -f docker-compose.dns.yml config --quiet
else
    echo "(docker compose not available, skipped)"
fi
echo "homelab-mediaserver checks passed"
