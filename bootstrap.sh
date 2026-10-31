#!/usr/bin/env bash
# ==============================================================================
# Homelab Blueprint - 1-Line Curl Bootstrap Runner
# Usage on fresh Ubuntu Server:
#   curl -sSL https://raw.githubusercontent.com/RAM-MAHESHWARI24/homelab-blueprint/main/bootstrap.sh | sudo bash
# Or with version pinning:
#   curl -sSL https://.../bootstrap.sh | sudo bash -s -- --version v1.0.0
# ==============================================================================

set -euo pipefail

TARGET_DIR="/opt/homelab-blueprint"
REPO_URL="https://github.com/RAM-MAHESHWARI24/homelab-blueprint.git"
REF_TARGET=""

usage() {
    cat <<EOF
Usage: sudo ./bootstrap.sh [OPTIONS]

Bootstrap and initialize the Homelab Blueprint on Ubuntu Server.

Options:
  --version <tag>     Pin to a specific immutable release tag (e.g. v1.0.0)
  --branch <name>     Check out an active development branch (e.g. develop)
  --dir <path>        Custom installation target directory (default: /opt/homelab-blueprint)
  -h, --help          Show this help message and exit
EOF
    exit 0
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --version)
            REF_TARGET="tags/$2"
            shift 2
            ;;
        --branch)
            REF_TARGET="$2"
            shift 2
            ;;
        --dir)
            TARGET_DIR="$2"
            shift 2
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo "❌ Unknown option: $1"
            echo "   Run './bootstrap.sh --help' for usage."
            exit 1
            ;;
    esac
done

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

# Clone or update repository
if [ -d "$TARGET_DIR/.git" ]; then
    echo "🔄 Existing repository found at $TARGET_DIR. Fetching latest updates..."
    cd "$TARGET_DIR"
    git fetch -q --all --tags
else
    echo "📥 Cloning Homelab Blueprint to $TARGET_DIR..."
    mkdir -p "$TARGET_DIR"
    git clone -q "$REPO_URL" "$TARGET_DIR"
    cd "$TARGET_DIR"
fi

# Apply version or branch target if specified
if [ -n "$REF_TARGET" ]; then
    echo "📌 Checking out specified target: $REF_TARGET..."
    git checkout -q "$REF_TARGET"
fi

# Make scripts executable
chmod +x setup.sh bootstrap.sh teardown.sh 2>/dev/null || true

# Launch Setup Wizard
echo "✨ Launching Homelab Setup Wizard..."
exec bash ./setup.sh
