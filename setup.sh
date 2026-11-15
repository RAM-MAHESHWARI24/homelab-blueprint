#!/usr/bin/env bash
# ==============================================================================
# Homelab Blueprint - Setup & Management CLI
# Zero-dependency bootstrap for a fresh Ubuntu Server
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

usage() {
    cat <<EOF
Homelab Blueprint Setup & Management CLI

Usage:
  sudo ./setup.sh                                   Launch the web setup wizard (prints a one-time token URL)
  sudo ./setup.sh --headless --config <file.json>   Unattended install from a JSON profile
  sudo ./setup.sh --headless --config <f> --dry-run Simulate an install without touching the host
  ./setup.sh --doctor                               Pre-flight host diagnostics (no root needed)
  sudo ./setup.sh --migrate [--check] [--dry-run]   Upgrade rendered .env files to the current schema
  sudo ./setup.sh token [--rotate]                  Show or rotate the Control Hub access token
  ./setup.sh --help                                 This message
EOF
}

case "${1:-}" in
    --help|-h|help)
        usage
        exit 0
        ;;
    --doctor|doctor|-d)
        exec python3 "$SCRIPT_DIR/setup/doctor.py"
        ;;
esac

# Everything below changes system state and needs root.
if [ "$EUID" -ne 0 ]; then
    echo "This command needs root (Docker, Netplan, systemd). Re-launching with sudo..."
    exec sudo bash "$0" "$@"
fi

case "${1:-}" in
    --migrate|migrate|-m)
        shift
        exec python3 "$SCRIPT_DIR/setup/installer/schema_migrator.py" "$@"
        ;;
    token)
        shift
        exec python3 "$SCRIPT_DIR/setup/token.py" "$@"
        ;;
esac

echo "============================================================"
echo "  Homelab Blueprint - Setup"
echo "============================================================"

# 1. Base packages the wizard and installer rely on
MISSING=()
command -v python3 >/dev/null 2>&1 || MISSING+=("python3")
dpkg -s python3-venv >/dev/null 2>&1 || MISSING+=("python3-venv")
command -v jq >/dev/null 2>&1 || MISSING+=("jq")
command -v curl >/dev/null 2>&1 || MISSING+=("curl")

if [ ${#MISSING[@]} -gt 0 ]; then
    echo "Installing prerequisites: ${MISSING[*]}"
    apt-get update -qq
    apt-get install -y -qq "${MISSING[@]}"
fi

# 2. Docker Engine + Compose v2 (Ubuntu packages; no curl|sh)
if ! command -v docker >/dev/null 2>&1; then
    echo "Installing Docker Engine and Compose v2..."
    apt-get update -qq
    apt-get install -y -qq docker.io docker-compose-v2
    systemctl enable --now docker
    if [ -n "${SUDO_USER:-}" ]; then
        usermod -aG docker "$SUDO_USER" 2>/dev/null || true
    fi
fi

# 3. Repository git hooks (developer convenience; harmless for end users)
if [ -d "$SCRIPT_DIR/.git" ] && [ -d "$SCRIPT_DIR/.githooks" ]; then
    git -C "$SCRIPT_DIR" config core.hooksPath .githooks 2>/dev/null || true
fi

# 4. Hand over to the Python installer
if [[ "${1:-}" == "--headless" || "${1:-}" == "-hl" ]]; then
    echo "Running unattended deployment..."
    exec python3 "$SCRIPT_DIR/setup/server.py" "$@"
fi

echo "Starting the web setup wizard..."
exec python3 "$SCRIPT_DIR/setup/server.py"
