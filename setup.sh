#!/usr/bin/env bash
# ==============================================================================
# Homelab Blueprint - Setup Wizard Launcher
# Zero-dependency bootstrap for fresh Ubuntu Server
# ==============================================================================

set -euo pipefail

# Ensure running with root/sudo for system-level configuration
if [ "$EUID" -ne 0 ]; then
    echo "⚠️ Homelab Setup Wizard requires root privileges to configure Netplan, Storage, and Docker."
    echo "   Re-launching with sudo..."
    exec sudo bash "$0" "$@"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "============================================================"
echo "  🏠 Initializing Homelab Blueprint Setup Wizard..."
echo "============================================================"

# 1. Verify and install Python 3 & venv
MISSING=()
if ! command -v python3 &>/dev/null; then MISSING+=("python3"); fi
if ! dpkg -s python3-venv &>/dev/null 2>&1; then MISSING+=("python3-venv"); fi
if ! command -v jq &>/dev/null; then MISSING+=("jq"); fi

if [ ${#MISSING[@]} -gt 0 ]; then
    echo "📦 Installing essential packages (${MISSING[*]})..."
    apt-get update -qq && apt-get install -y -qq "${MISSING[@]}"
fi

# 2. Check Docker availability & install if missing
if ! command -v docker &>/dev/null; then
    echo "📦 Docker Engine not detected. Installing docker.io & docker-compose-v2..."
    apt-get update -qq && apt-get install -y -qq docker.io docker-compose-v2
    systemctl enable --now docker
    if [ -n "${SUDO_USER:-}" ]; then
        usermod -aG docker "$SUDO_USER" 2>/dev/null || true
    fi
    echo "✅ Docker Engine installed and running."
fi

# 3. Ensure unprivileged system user 'homelab' exists for background daemon
if ! id -u homelab &>/dev/null; then
    useradd -r -s /usr/sbin/nologin -G docker homelab 2>/dev/null || true
fi

# 4. Launch the zero-dependency Python Setup Daemon
echo "🚀 Starting Web GUI daemon..."
exec python3 "$SCRIPT_DIR/setup/server.py"
