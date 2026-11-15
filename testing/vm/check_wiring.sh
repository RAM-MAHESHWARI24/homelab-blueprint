#!/usr/bin/env bash
# Runs inside an installed host (VM or CI runner) and asserts the apps are wired
# together, not just running. Used by testing/vm/test_wizard_gui.py after a GUI install.
#
#   sudo bash check_wiring.sh [--photos]
#
# Exits non-zero on the first failed check; `set -x` names it in the output.
set -euo pipefail

APPDATA="${HOMELAB_APPDATA_DIR:-/srv/homelab/appdata}/mediaserver"
CHECK_PHOTOS=false
[ "${1:-}" = "--photos" ] && CHECK_PHOTOS=true

key() { grep -oP '(?<=<ApiKey>)[^<]+' "$APPDATA/$1/config.xml"; }

set -x
RADARR_KEY="$(key radarr)"
SONARR_KEY="$(key sonarr)"
PROWLARR_KEY="$(key prowlarr)"

curl -fsS -H "X-Api-Key: $RADARR_KEY" http://127.0.0.1:7878/api/v3/downloadclient | grep -qE '"name": *"qBittorrent"'
curl -fsS -H "X-Api-Key: $RADARR_KEY" http://127.0.0.1:7878/api/v3/rootfolder | grep -q '/data/media/movies'
curl -fsS -H "X-Api-Key: $SONARR_KEY" http://127.0.0.1:8989/api/v3/downloadclient | grep -qE '"name": *"qBittorrent"'
curl -fsS -H "X-Api-Key: $SONARR_KEY" http://127.0.0.1:8989/api/v3/rootfolder | grep -q '/data/media/tv'
curl -fsS -H "X-Api-Key: $PROWLARR_KEY" http://127.0.0.1:9696/api/v1/applications | grep -qE '"name": *"Radarr"'
curl -fsS -H "X-Api-Key: $PROWLARR_KEY" http://127.0.0.1:9696/api/v1/applications | grep -qE '"name": *"Sonarr"'
curl -fsS http://127.0.0.1:8096/System/Info/Public | grep -qE '"StartupWizardCompleted": *true'
curl -fsS http://127.0.0.1:5055/api/v1/settings/public | grep -qE '"initialized": *true'

# qBittorrent: the generated password works and anonymous access is refused
QB_PASS="$(grep -oP '(?<=^QBITTORRENT_PASS=).*' /etc/homelab/mediaserver.env)"
QB_LOGIN="$(curl -s -o /dev/null -w '%{http_code}' -c /tmp/qb.jar --data-urlencode "username=admin" --data-urlencode "password=$QB_PASS" http://127.0.0.1:8080/api/v2/auth/login)"
test "$QB_LOGIN" = 200 -o "$QB_LOGIN" = 204
grep -q QBT_SID /tmp/qb.jar
curl -fsS -b /tmp/qb.jar http://127.0.0.1:8080/api/v2/app/version
test "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/api/v2/app/version)" = "403"

# Control Hub: token works, anonymous refused, Prowlarr key readable by the service user
TOKEN="$(cat /etc/homelab/control-hub.token)"
curl -fsS -H "Authorization: Bearer $TOKEN" http://127.0.0.1:7575/api/auth/check | grep -q authenticated
test "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:7575/api/system/vitals)" = "401"
stat -c '%a %G' /etc/homelab/prowlarr.key | grep -q '^640 homelab$'
systemctl is-active --quiet control-hub.service

if $CHECK_PHOTOS; then
    curl -fsS http://127.0.0.1:2283/api/server/ping | grep -q pong
    # The photo database lives under appdata, not inside the checkout
    test -d "${HOMELAB_APPDATA_DIR:-/srv/homelab/appdata}/noodle-gallery/postgres"
fi

set +x
echo "WIRING OK"
