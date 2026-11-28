#!/usr/bin/env python3
"""
Control Hub token management.

    sudo ./setup.sh token            show the current token and dashboard URL
    sudo ./setup.sh token --rotate   generate a new token, update the env file, restart the daemon
"""

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import setup  # noqa: F401
from core.config_core import (
    CONTROL_HUB_TOKEN_FILE,
    SERVICE_USER,
    generate_token,
    read_token_file,
    write_token_file,
    load_env_file,
    update_env_variables,
    write_env_file,
    module_env_file,
    probe_network_interfaces,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Show or rotate the Control Hub access token")
    parser.add_argument("--rotate", action="store_true", help="Generate a new token and restart control-hub.service")
    args = parser.parse_args()

    env_path = module_env_file("control-hub")
    current = read_token_file(CONTROL_HUB_TOKEN_FILE) or load_env_file(str(env_path)).get("CONTROL_HUB_TOKEN")

    if args.rotate:
        token = generate_token()
        write_token_file(token, CONTROL_HUB_TOKEN_FILE, group=SERVICE_USER)
        if env_path.exists():
            content = update_env_variables(env_path.read_text(encoding="utf-8"), {"CONTROL_HUB_TOKEN": token})
            write_env_file(str(env_path), content, mode=0o640)
        subprocess.run(["systemctl", "restart", "control-hub.service"], capture_output=True, timeout=60)
        current = token
        print("Token rotated and control-hub.service restarted.")

    if not current:
        print("No Control Hub token found. Run the setup wizard first.", file=sys.stderr)
        return 1

    net = probe_network_interfaces()
    port = load_env_file(str(env_path)).get("CONTROL_HUB_PORT", "7575")
    print(f"Control Hub token: {current}")
    print(f"Dashboard:         http://{net['current_ip']}:{port}/  (paste the token when asked)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
