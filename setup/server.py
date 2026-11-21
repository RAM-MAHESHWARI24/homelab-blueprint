#!/usr/bin/env python3
"""
Homelab Blueprint - Setup Wizard web server, REST API and headless runner.

Standard library only (ADR-0002). Runs as root on a fresh Ubuntu Server, so
every privileged endpoint requires the one-time token printed at startup:

    http://<lan-ip>:8000/?token=<token>

The page stores the token in sessionStorage and sends it as
`Authorization: Bearer <token>`. Static assets and /api/health are public.
After a successful non-dry-run deployment the server exits on its own. If the
deployment left a static-IP change pending, it stays up (it listens on every
address, so it answers on the new IP) until the change is confirmed or the
revert window has passed.
"""

import json
import mimetypes
import os
import sys
import threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def safe_print(text: str) -> None:
    try:
        print(text, flush=True)
    except (UnicodeEncodeError, UnicodeError):
        print(text.encode("ascii", errors="replace").decode("ascii"), flush=True)


BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import setup  # noqa: F401  (adds apps/control-hub to sys.path)
from core.config_core import (
    get_system_snapshot,
    generate_ai_context_dump,
    generate_all_secrets,
    generate_token,
    extract_token,
    token_matches,
    test_atomic_hardlink,
    verify_path_writable,
    check_ports_matrix,
    get_default_ports,
    generate_netplan_yaml,
    confirm_netplan_change,
    netplan_change_status,
)
from setup.installer import deploy_homelab_stack

PORT = int(os.getenv("SETUP_PORT", 8000))
HOST = os.getenv("SETUP_HOST", "0.0.0.0")
STATIC_DIR = BASE_DIR / "static"
MAX_BODY_BYTES = 256 * 1024
EXIT_AFTER_DEPLOY_SEC = int(os.getenv("SETUP_EXIT_DELAY", "15"))
# Extra time the wizard stays up after an unconfirmed static-IP revert window ends.
NETPLAN_EXIT_GRACE_SEC = 60

# Token for this wizard run. SETUP_TOKEN lets tests and automation pin it.
SETUP_TOKEN = os.getenv("SETUP_TOKEN") or generate_token()
PUBLIC_API_PATHS = {"/api/health"}


class SetupApiHandler(BaseHTTPRequestHandler):
    """Static assets plus the token-protected setup REST API."""

    server_version = "HomelabSetupWizard/2.0"
    # Overridable for tests (class attribute so threads share it)
    token = SETUP_TOKEN
    # Set once a real deployment succeeded; a later netplan confirm then ends the wizard.
    deployed = False

    # ------------------------------------------------------------ helpers
    def log_message(self, fmt, *args):  # quieter default logging
        if os.getenv("SETUP_VERBOSE"):
            super().log_message(fmt, *args)

    def send_json(self, data: dict, status_code: int = 200) -> None:
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def read_json_body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            return {}
        if length <= 0:
            return {}
        if length > MAX_BODY_BYTES:
            raise ValueError("request body too large")
        raw = self.rfile.read(length).decode("utf-8")
        data = json.loads(raw) if raw.strip() else {}
        return data if isinstance(data, dict) else {}

    def authorized(self) -> bool:
        return token_matches(extract_token(self.headers), self.token)

    def require_auth(self) -> bool:
        if self.authorized():
            return True
        self.send_json({"error": "unauthorized", "hint": "Open the wizard with the ?token=... URL printed in the terminal."}, 401)
        return False

    # ------------------------------------------------------------- routes
    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/api/health":
            self.send_json({"status": "healthy", "service": "Homelab Setup Wizard", "version": "2.1.1"})
            return

        if path.startswith("/api/"):
            if not self.require_auth():
                return
            if path == "/api/probe":
                self.send_json(get_system_snapshot())
            elif path == "/api/ai/context":
                snapshot = get_system_snapshot()
                self.send_json({"prompt": generate_ai_context_dump(snapshot), "snapshot": snapshot})
            elif path == "/api/ports/default":
                self.send_json({"ports": get_default_ports()})
            elif path == "/api/netplan/status":
                self.send_json(netplan_change_status())
            else:
                self.send_json({"error": f"Unknown endpoint: {path}"}, 404)
            return

        self.serve_static(path)

    def do_POST(self):
        path = urlparse(self.path).path
        if not path.startswith("/api/"):
            self.send_json({"error": "not found"}, 404)
            return
        if not self.require_auth():
            return

        try:
            body = self.read_json_body()
        except (ValueError, json.JSONDecodeError) as e:
            self.send_json({"error": f"invalid request body: {e}"}, 400)
            return

        if path == "/api/verify/hardlink":
            target = body.get("path", "")
            if not target:
                self.send_json({"error": "Path required"}, 400)
                return
            self.send_json(test_atomic_hardlink(target))

        elif path == "/api/verify/path":
            target = body.get("path", "")
            if not target:
                self.send_json({"error": "Path required"}, 400)
                return
            self.send_json(verify_path_writable(target))

        elif path == "/api/verify/ports":
            self.send_json(check_ports_matrix(body.get("ports", {})))

        elif path == "/api/secrets/generate":
            self.send_json(generate_all_secrets())

        elif path == "/api/verify/netplan":
            iface = body.get("interface", "")
            ip = body.get("ip", "")
            if not iface or not ip:
                self.send_json({"valid": False, "error": "interface and ip are required"}, 400)
                return
            ip_cidr = ip if "/" in ip else f"{ip}/24"
            yaml_preview = generate_netplan_yaml(iface, ip_cidr, body.get("gateway", ""), body.get("dns", ["1.1.1.1", "8.8.8.8"]))
            self.send_json({"valid": True, "preview_yaml": yaml_preview})

        elif path == "/api/netplan/confirm":
            # Exit timers are armed before the response is sent, so a client that sees
            # the response can rely on the wizard's shutdown already being scheduled.
            result = confirm_netplan_change()
            if result.get("success") and SetupApiHandler.deployed:
                safe_print("\nStatic IP confirmed.")
                self.schedule_exit(EXIT_AFTER_DEPLOY_SEC)
            self.send_json(result)

        elif path == "/api/deploy":
            result = deploy_homelab_stack(str(REPO_ROOT), body)
            if result.get("success") and not result.get("dry_run"):
                SetupApiHandler.deployed = True
                netplan = result.get("netplan_result") or {}
                if netplan.get("pending"):
                    # The browser confirms from the new address, so stay up until then. If nobody
                    # confirms, the timer reverts the network and the wizard exits after a grace period.
                    window = int(netplan.get("timeout_sec") or 120)
                    safe_print(f"\nDeployment finished. Static IP pending confirmation (reverts in {window}s).")
                    self.schedule_exit(window + NETPLAN_EXIT_GRACE_SEC)
                else:
                    safe_print("\nDeployment finished.")
                    self.schedule_exit(EXIT_AFTER_DEPLOY_SEC)
            self.send_json(result)

        else:
            self.send_json({"error": f"Unknown endpoint: {path}"}, 404)

    def schedule_exit(self, delay_sec: int) -> None:
        """Stops the wizard after `delay_sec` (0 or less disables auto-exit, e.g. in tests)."""
        if delay_sec <= 0 or EXIT_AFTER_DEPLOY_SEC <= 0:
            return
        safe_print(f"Setup wizard will exit in {delay_sec}s.")
        timer = threading.Timer(delay_sec, self.server.shutdown)
        timer.daemon = True
        timer.start()

    # ------------------------------------------------------------- static
    def serve_static(self, req_path: str) -> None:
        static_root = STATIC_DIR.resolve()
        rel = req_path.lstrip("/") or "index.html"
        try:
            resolved = (static_root / rel).resolve()
        except (OSError, RuntimeError):
            self.send_json({"error": "not found"}, 404)
            return

        if not resolved.is_relative_to(static_root):
            self.send_response(403)
            self.end_headers()
            return

        if not resolved.is_file():
            resolved = static_root / "index.html"  # SPA fallback
            if not resolved.is_file():
                self.send_response(404)
                self.end_headers()
                return

        mime_type, _ = mimetypes.guess_type(str(resolved))
        if resolved.suffix == ".css":
            mime_type = "text/css"
        elif resolved.suffix == ".js":
            mime_type = "application/javascript"
        mime_type = mime_type or "application/octet-stream"

        content = resolved.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", f"{mime_type}; charset=utf-8" if mime_type.startswith("text/") or mime_type.endswith("javascript") else mime_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(content)


def _display_ip() -> str:
    try:
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("1.1.1.1", 80))
            return s.getsockname()[0]
    except Exception:
        return "localhost"


def run_server() -> None:
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    httpd = ThreadingHTTPServer((HOST, PORT), SetupApiHandler)
    httpd.daemon_threads = True
    ip = _display_ip()

    safe_print(
        f"""
+------------------------------------------------------------------------+
|                   HOMELAB BLUEPRINT SETUP WIZARD                       |
+------------------------------------------------------------------------+
|  Open this exact link (it carries your one-time access token):         |
|                                                                        |
|    http://{ip}:{PORT}/?token={SETUP_TOKEN}
|                                                                        |
|  Anyone with the link can configure this server. Do not share it.      |
|  The wizard exits automatically after a successful deployment.         |
|  Press Ctrl+C to stop it at any time.                                  |
+------------------------------------------------------------------------+
"""
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        safe_print("\nSetup wizard stopped.")
    finally:
        httpd.server_close()


def run_headless(config_path: str, dry_run: bool = False) -> int:
    path = Path(config_path).resolve()
    if not path.is_file():
        safe_print(f"Error: config file not found at '{path}'")
        return 1
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        safe_print(f"Error parsing JSON config: {e}")
        return 1

    if dry_run:
        config["dry_run"] = True
    config["_headless"] = True

    safe_print(f"Loaded configuration from {path}")
    safe_print(f"Starting provisioning (dry_run={config.get('dry_run', False)})...")
    result = deploy_homelab_stack(str(REPO_ROOT), config)

    safe_print("\n" + "=" * 60 + "\n  DEPLOYMENT LOG\n" + "=" * 60)
    for line in result.get("logs", []):
        safe_print(f"  {line}")

    if result.get("success"):
        creds = result.get("credentials", {})
        safe_print("\nDeployment completed successfully.")
        safe_print(f"  Control Hub: {result.get('dashboard_url')}")
        if creds.get("control_hub_token"):
            safe_print(f"  Control Hub token: {creds['control_hub_token']}")
            safe_print("  (also stored in /etc/homelab/control-hub.token; show again with ./setup.sh token)")
        return 0

    safe_print("\nDeployment encountered errors:")
    for err in result.get("errors", []):
        safe_print(f"  - [{err.get('service')}] {err.get('msg')}")
    return 1


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Homelab Blueprint Setup Wizard & API daemon")
    parser.add_argument("--headless", action="store_true", help="Run an unattended deployment from --config")
    parser.add_argument("--config", type=str, default="", help="Path to a JSON configuration file")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without modifying the host")
    args = parser.parse_args()

    if args.headless:
        if not args.config:
            safe_print("Error: --headless requires --config <path.json>")
            sys.exit(1)
        sys.exit(run_headless(args.config, dry_run=args.dry_run))
    run_server()
