#!/usr/bin/env bash
# Checks for the standalone tv-autoupdater repo. Run by its own CI workflow, and by the
# homelab-blueprint split-simulation job against an isolated copy of this folder.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

echo "== requirements, compile and CLI parsing"
python3 -m pip install -q -r requirements.txt
python3 -m py_compile tv_updater.py
python3 tv_updater.py --help >/dev/null

echo "== example config has pinned signing keys"
python3 - <<'PY'
import json
text = json.dumps(json.load(open("config.example.json"))).lower()
assert "sha256" in text or "signature" in text, "no pinned signing keys in config.example.json"
PY

if command -v shellcheck >/dev/null; then
    echo "== shellcheck"
    shellcheck --severity=warning install.sh ci.sh setup_cron.sh
else
    echo "(shellcheck not installed, skipped)"
fi
echo "tv-autoupdater checks passed"
