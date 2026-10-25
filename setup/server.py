#!/usr/bin/env python3
"""
Homelab Blueprint - Zero-Dependency Setup Wizard Web Server & REST API
Built using Python 3 standard library (no pip dependencies required).
Runs on fresh Ubuntu Server immediately out of the box.
"""

import json
import mimetypes
import os
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

# Ensure stdout handles UTF-8 on minimal Linux locales (C/POSIX) and Windows cp1252
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

def safe_print(text: str):
    """Prints text cleanly, falling back to ASCII replacement if terminal lacks UTF-8"""
    try:
        print(text, flush=True)
    except (UnicodeEncodeError, UnicodeError):
        safe_text = text.encode("ascii", errors="replace").decode("ascii")
        print(safe_text, flush=True)

# Ensure monorepo root is importable
BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from setup.config_core import (
    get_system_snapshot,
    generate_ai_context_dump,
    generate_all_secrets,
    test_atomic_hardlink,
    verify_path_writable,
    check_ports_matrix,
    get_default_ports,
    generate_netplan_yaml,
    safe_apply_netplan,
    deploy_homelab_stack
)

PORT = int(os.getenv("SETUP_PORT", 8000))
HOST = os.getenv("SETUP_HOST", "0.0.0.0")
STATIC_DIR = BASE_DIR / "static"


class SetupApiHandler(BaseHTTPRequestHandler):
    """Handles static assets and setup REST API requests"""

    server_version = "HomelabSetupWizard/1.0"

    def send_json(self, data: dict, status_code: int = 200):
        """Sends a JSON response with CORS headers"""
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def read_json_body(self) -> dict:
        """Helper to parse JSON from request body"""
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length > 0:
                raw_data = self.rfile.read(content_length).decode("utf-8")
                return json.loads(raw_data)
        except Exception:
            pass
        return {}

    def do_OPTIONS(self):
        """Handle CORS pre-flight requests"""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        """Route GET requests: APIs and static frontend files"""
        parsed = urlparse(self.path)
        path = parsed.path

        # REST API Routes
        if path == "/api/probe":
            snapshot = get_system_snapshot()
            self.send_json(snapshot)
            return

        elif path == "/api/ai/context":
            snapshot = get_system_snapshot()
            prompt = generate_ai_context_dump(snapshot)
            self.send_json({"prompt": prompt, "snapshot": snapshot})
            return

        elif path == "/api/ports/default":
            ports = get_default_ports()
            self.send_json({"ports": ports})
            return

        elif path == "/api/health":
            self.send_json({"status": "healthy", "service": "Homelab Setup Wizard"})
            return

        # Serve Static Files
        self.serve_static(path)

    def do_POST(self):
        """Route POST requests for live verification, password generation, and deployment"""
        parsed = urlparse(self.path)
        path = parsed.path
        body = self.read_json_body()

        if path == "/api/verify/hardlink":
            target_path = body.get("path", "")
            if not target_path:
                self.send_json({"error": "Path required"}, 400)
                return
            result = test_atomic_hardlink(target_path)
            self.send_json(result)
            return

        elif path == "/api/verify/path":
            target_path = body.get("path", "")
            if not target_path:
                self.send_json({"error": "Path required"}, 400)
                return
            result = verify_path_writable(target_path)
            self.send_json(result)
            return

        elif path == "/api/verify/ports":
            ports_to_check = body.get("ports", {})
            result = check_ports_matrix(ports_to_check)
            self.send_json(result)
            return

        elif path == "/api/secrets/generate":
            secrets = generate_all_secrets()
            self.send_json(secrets)
            return

        elif path == "/api/verify/netplan":
            iface = body.get("interface", "eth0")
            ip = body.get("ip", "192.168.1.100")
            gw = body.get("gateway", "192.168.1.1")
            dns = body.get("dns", ["1.1.1.1", "8.8.8.8"])
            yaml_preview = generate_netplan_yaml(iface, ip, gw, dns)
            self.send_json({
                "valid": True,
                "preview_yaml": yaml_preview,
            })
            return

        elif path == "/api/deploy":
            # Run the complete deployment orchestrator
            result = deploy_homelab_stack(str(REPO_ROOT), body)
            self.send_json(result)
            return

        else:
            self.send_json({"error": f"Unknown endpoint: {path}"}, 404)

    def serve_static(self, req_path: str):
        """Serves HTML, CSS, JS, and image assets from setup/static/"""
        if req_path == "/" or not req_path:
            file_path = STATIC_DIR / "index.html"
        else:
            rel_path = req_path.lstrip("/")
            file_path = STATIC_DIR / rel_path

        # Security check: Prevent path traversal outside STATIC_DIR
        try:
            resolved_path = file_path.resolve()
            if not str(resolved_path).startswith(str(STATIC_DIR.resolve())):
                self.send_response(403)
                self.end_headers()
                self.wfile.write(b"403 Forbidden")
                return
        except Exception:
            self.send_response(404)
            self.end_headers()
            return

        if not resolved_path.exists() or resolved_path.is_dir():
            # If requesting a path that doesn't exist, serve index.html (SPA fallback)
            fallback = STATIC_DIR / "index.html"
            if fallback.exists():
                resolved_path = fallback
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"404 Not Found")
                return

        mime_type, _ = mimetypes.guess_type(str(resolved_path))
        if not mime_type:
            mime_type = "application/octet-stream"
        if resolved_path.suffix == ".css":
            mime_type = "text/css"
        elif resolved_path.suffix == ".js":
            mime_type = "application/javascript"

        try:
            content = resolved_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", f"{mime_type}; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(f"500 Internal Error: {e}".encode("utf-8"))


def run_server():
    """Starts the zero-dependency HTTP server daemon"""
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    server_address = (HOST, PORT)
    httpd = HTTPServer(server_address, SetupApiHandler)

    # Determine display IP
    display_ip = "localhost"
    try:
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("1.1.1.1", 80))
            display_ip = s.getsockname()[0]
    except Exception:
        pass

    banner = f"""
+------------------------------------------------------------------------+
|                   HOMELAB BLUEPRINT SETUP WIZARD                       |
+------------------------------------------------------------------------+
|  Setup server is online and waiting!                                   |
|                                                                        |
|  Access the Web GUI from your browser:                                 |
|  * LAN URL:   http://{display_ip}:{PORT}   (from laptop / phone)       |
|  * Local URL: http://localhost:{PORT}       (from this server)         |
|                                                                        |
|  Press Ctrl+C to terminate the setup wizard at any time.               |
+------------------------------------------------------------------------+
"""
    safe_print(banner)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        safe_print("\n🛑 Homelab Setup Wizard stopped by user.")
        httpd.server_close()


if __name__ == "__main__":
    run_server()
