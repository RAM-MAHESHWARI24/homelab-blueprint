#!/usr/bin/env bash
# ==============================================================================
# Homelab Blueprint - 1-Line Curl Bootstrap Runner
# Usage on fresh Ubuntu Server:
#   curl -sSL https://raw.githubusercontent.com/RAM-MAHESHWARI24/homelab-blueprint/main/bootstrap.sh | sudo bash
# ==============================================================================

set -euo pipefail

TARGET_DIR="/opt/homelab-blueprint"
REPO_URL="https://github.com/RAM-MAHESHWARI24/homelab-blueprint.git"

echo "============================================================"
echo "  ⚡ Homelab Blueprint - Automated 1-Line Bootstrap"
echo "============================================================"

# Ensure root privileges
if [ "$EUID" -ne 0 ]; then
    echo "❌ Please run as root or with sudo:"
    echo "   curl -sSL ... | sudo bash"
    exit 1
fi

# Ensure git, python3, and curl are installed
MISSING_PKGS=()
if ! command -v git &>/dev/null; then MISSING_PKGS+=("git"); fi
if ! command -v python3 &>/dev/null; then MISSING_PKGS+=("python3"); fi
if ! command -v curl &>/dev/null; then MISSING_PKGS+=("curl"); fi

if [ ${#MISSING_PKGS[@]} -gt 0 ]; then
    echo "📦 Installing prerequisites (${MISSING_PKGS[*]})..."
    apt-get update -qq
    apt-get install -y -qq "${MISSING_PKGS[@]}"
fi

# Clone or pull latest
if [ -d "$TARGET_DIR/.git" ]; then
    echo "🔄 Existing repository found at $TARGET_DIR. Pulling latest updates..."
    cd "$TARGET_DIR"
    git pull -q
else
    echo "📥 Cloning Homelab Blueprint to $TARGET_DIR..."
    mkdir -p "$TARGET_DIR"
    git clone -q "$REPO_URL" "$TARGET_DIR"
    cd "$TARGET_DIR"
fi

# Make scripts executable
chmod +x setup.sh bootstrap.sh 2>/dev/null || true

# Launch Setup Wizard
echo "✨ Launching Homelab Setup Wizard..."
exec bash ./setup.sh
