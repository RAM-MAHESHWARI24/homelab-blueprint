#!/usr/bin/env bash
# ==============================================================================
# homelab-mediaserver - standalone install (outside the homelab-blueprint installer)
#
#   ./install.sh [--data-dir /mnt/hdd/data] [--byparr]
#
# 1. Creates .env from .env.example once, with generated passwords and your UID/GID.
# 2. Creates the single-mount data tree (torrents/ and media/ on one filesystem,
#    so Radarr and Sonarr can hardlink instead of copying).
# 3. Seeds qBittorrent's config with the password, starts the stack and waits
#    until every container is healthy.
# 4. Wires the apps together with scripts/wire_arr.py: download clients, root
#    folders, Prowlarr app sync, Jellyfin libraries and Seerr.
# 5. Applies the release profiles in profiles/ (choices: MEDIA_* in .env).
#
# Indexers are not added: pick them in Prowlarr (http://<host>:9696). Which
# indexers you use, and whether they are legal where you live, is up to you.
# Safe to re-run: existing config and .env are kept, wiring skips what exists.
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

DATA_DIR_ARG=""
BYPARR=""
while [ $# -gt 0 ]; do
    case "$1" in
        --data-dir) DATA_DIR_ARG="$2"; shift 2 ;;
        --byparr) BYPARR="--byparr"; shift ;;
        -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
        *) echo "Unknown option: $1 (try --help)" >&2; exit 2 ;;
    esac
done

command -v docker >/dev/null || { echo "Docker is required." >&2; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "Docker Compose v2 is required." >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 is required." >&2; exit 1; }

env_get() { grep -E "^$1=" .env | head -n1 | cut -d= -f2- || true; }
env_set() {
    python3 - "$1" "$2" <<'PY'
import re, sys
key, value = sys.argv[1], sys.argv[2]
text = open(".env", encoding="utf-8").read()
if re.search(rf"^{re.escape(key)}=", text, flags=re.M):
    text = re.sub(rf"^{re.escape(key)}=.*$", f"{key}={value}", text, flags=re.M)
else:
    text += f"\n{key}={value}\n"
open(".env", "w", encoding="utf-8").write(text)
PY
}
gen() { python3 -c 'import secrets, string; a = string.ascii_letters + string.digits; print("".join(secrets.choice(a) for _ in range(20)))'; }

OWNER_UID="$(id -u "${SUDO_USER:-$(id -un)}")"
OWNER_GID="$(id -g "${SUDO_USER:-$(id -un)}")"

if [ ! -f .env ]; then
    cp .env.example .env
    chmod 600 .env
    env_set PUID "$OWNER_UID"
    env_set PGID "$OWNER_GID"
    env_set QBITTORRENT_PASS "$(gen)"
    env_set MEDIA_ADMIN_PASS "$(gen)"
    [ -n "$BYPARR" ] && env_set COMPOSE_PROFILES byparr
    echo "Created .env with generated passwords."
fi
[ -n "$DATA_DIR_ARG" ] && env_set DATA_DIR "$DATA_DIR_ARG"
[ -z "$(env_get MEDIA_ADMIN_PASS)" ] && env_set MEDIA_ADMIN_PASS "$(gen)"

DATA_DIR="$(env_get DATA_DIR)"; DATA_DIR="${DATA_DIR:-/mnt/hdd/data}"
CONFIG_DIR="$(env_get CONFIG_DIR)"; CONFIG_DIR="${CONFIG_DIR:-./config}"
QB_USER="$(env_get QBITTORRENT_USER)"; QB_USER="${QB_USER:-admin}"
QB_PASS="$(env_get QBITTORRENT_PASS)"
ADMIN_PASS="$(env_get MEDIA_ADMIN_PASS)"
PUID="$(env_get PUID)"; PGID="$(env_get PGID)"

echo "Creating the data tree under $DATA_DIR ..."
for d in torrents/movies torrents/tv media/movies media/tv; do
    mkdir -p "$DATA_DIR/$d"
done
mkdir -p "$CONFIG_DIR"
if [ "$(id -u)" -eq 0 ]; then
    chown -R "$PUID:$PGID" "$DATA_DIR/torrents" "$DATA_DIR/media" "$CONFIG_DIR"
fi

python3 scripts/wire_arr.py seed --config-dir "$CONFIG_DIR" --qbit-user "$QB_USER" --qbit-pass "$QB_PASS" --puid "$PUID" --pgid "$PGID"

echo "Starting the stack (first start pulls several GB of images) ..."
docker compose --env-file .env up -d --wait --wait-timeout 900

# Release profiles (profiles/): on for a new .env. An older .env without the key keeps
# whatever manages profiles today; set MEDIA_PROFILES=on and run profiles migrate to switch.
PROFILES="$(env_get MEDIA_PROFILES)"
if [ "$PROFILES" = "on" ]; then
    python3 scripts/wire_arr.py wire --config-dir "$CONFIG_DIR" --host 127.0.0.1 \
        --qbit-user "$QB_USER" --qbit-pass "$QB_PASS" --admin-pass "$ADMIN_PASS" --skip-seerr $BYPARR
    python3 scripts/wire_arr.py profiles apply --config-dir "$CONFIG_DIR" --host 127.0.0.1 \
        --env-file .env --data-dir "$DATA_DIR" --puid "$PUID" --pgid "$PGID"
    DEFAULT_PROFILE="1080p Compact"
    [ "$(env_get MEDIA_DEFAULT_PROFILE)" = "family" ] && DEFAULT_PROFILE="1080p Family"
    python3 scripts/wire_arr.py seerr --config-dir "$CONFIG_DIR" --host 127.0.0.1 \
        --admin-pass "$ADMIN_PASS" --profile "$DEFAULT_PROFILE"
else
    python3 scripts/wire_arr.py wire --config-dir "$CONFIG_DIR" --host 127.0.0.1 \
        --qbit-user "$QB_USER" --qbit-pass "$QB_PASS" --admin-pass "$ADMIN_PASS" $BYPARR
fi

cat <<EOF

Done. Save these credentials (they are also in .env, mode 0600):
  qBittorrent      http://<host>:8080   ${QB_USER} / ${QB_PASS}
  Jellyfin, Seerr  http://<host>:8096, http://<host>:5055   admin / ${ADMIN_PASS}
  Prowlarr         http://<host>:9696   add your indexers here
EOF
