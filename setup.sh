#!/usr/bin/env bash
# ==============================================================================
# Homelab Blueprint - Setup Wizard Launcher
# Zero-dependency bootstrap for fresh Ubuntu Server
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "============================================================"
echo "  🏠 Initializing Homelab Blueprint Setup Wizard..."
echo "============================================================"

# 1. Verify Python 3
if ! command -v python3 &>/dev/null; then
    echo "⚠️ Python 3 not detected. Installing python3 via apt-get..."
    sudo apt-get update && sudo apt-get install -y python3
fi

# 2. Check Docker availability
if ! command -v docker &>/dev/null; then
    echo "ℹ️ Note: Docker Engine not detected on host."
    echo "   The setup wizard will allow you to install Docker, or you can run:"
    echo "   sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2"
fi

# 3. Launch the zero-dependency Python Setup Daemon
echo "🚀 Starting Web GUI daemon..."
exec python3 "$SCRIPT_DIR/setup/server.py"
