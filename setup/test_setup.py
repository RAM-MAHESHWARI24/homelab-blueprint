"""
Verification test for the Homelab Blueprint Setup Wizard server and REST API.

Runs the wizard on an ephemeral localhost port with a fixed token and checks:
health (public), token enforcement (401 without, 200 with), hardware probe,
hardlink verification, secrets generation, static assets and a dry-run deploy.
"""

import json
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from setup.server import SetupApiHandler

TEST_TOKEN = "wizard-test-token-0123456789"
PORT = 8089
BASE = f"http://127.0.0.1:{PORT}"
AUTH = {"Authorization": f"Bearer {TEST_TOKEN}"}


def request(path: str, data=None, auth: bool = True, method: str = None):
    headers = {"Content-Type": "application/json"}
    if auth:
        headers.update(AUTH)
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(BASE + path, data=body, headers=headers, method=method or ("POST" if body is not None else "GET"))
    with urllib.request.urlopen(req, timeout=30) as res:
        raw = res.read()
        return res.status, (json.loads(raw.decode()) if res.headers.get("Content-Type", "").startswith("application/json") else raw.decode())


def test_exit_waits_for_netplan_confirm():
    """A real deploy with a pending static IP must keep the wizard up until confirm.

    The deployer and the exit timer are stubbed: no host changes, no shutdown.
    """
    import setup.server as wizard

    print("Testing wizard stays up while a static-IP change is pending...")
    scheduled = []
    original_deploy = wizard.deploy_homelab_stack
    original_exit = SetupApiHandler.schedule_exit
    original_confirm = wizard.confirm_netplan_change
    try:
        SetupApiHandler.schedule_exit = lambda self, delay: scheduled.append(delay)
        wizard.confirm_netplan_change = lambda: {"success": True, "message": "confirmed (stub)"}

        wizard.deploy_homelab_stack = lambda root, cfg: {
            "success": True, "dry_run": False,
            "netplan_result": {"success": True, "pending": True, "ip": "192.168.1.50/24", "timeout_sec": 120},
        }
        status, _ = request("/api/deploy", {"mode": "express"})
        assert status == 200
        assert scheduled == [120 + wizard.NETPLAN_EXIT_GRACE_SEC], f"pending IP: expected revert window + grace, got {scheduled}"

        status, data = request("/api/netplan/confirm", {})
        assert status == 200 and data["success"], data
        assert scheduled[-1] == wizard.EXIT_AFTER_DEPLOY_SEC, f"confirm should schedule the normal exit, got {scheduled}"

        scheduled.clear()
        wizard.deploy_homelab_stack = lambda root, cfg: {"success": True, "dry_run": False, "netplan_result": {"success": True}}
        request("/api/deploy", {"mode": "express"})
        assert scheduled == [wizard.EXIT_AFTER_DEPLOY_SEC], f"no pending IP: expected normal exit, got {scheduled}"
    finally:
        wizard.deploy_homelab_stack = original_deploy
        wizard.confirm_netplan_change = original_confirm
        SetupApiHandler.schedule_exit = original_exit
        SetupApiHandler.deployed = False


def test_photos_image_override():
    """Existing photo libraries can pin their running images; floating tags are refused."""
    from setup.installer.deployer import Deployment

    print("Testing photo image pins for existing libraries...")
    root = Path(__file__).resolve().parent.parent
    d = Deployment(str(root), {"dry_run": True})
    assert d.photos_image_override() == (True, None)

    d = Deployment(str(root), {"dry_run": True, "photos_server_image": "ghcr.io/immich-app/immich-server:v1.140.1",
                               "photos_ml_image": "ghcr.io/immich-app/immich-machine-learning@sha256:" + "a" * 64})
    ok, yml = d.photos_image_override()
    assert ok and "gallery-server:\n    image: ghcr.io/immich-app/immich-server:v1.140.1" in yml, yml
    assert "gallery-machine-learning:" in yml

    for bad in ("ghcr.io/immich-app/immich-server", "ghcr.io/immich-app/immich-server:release", "x:latest"):
        d = Deployment(str(root), {"dry_run": True, "photos_server_image": bad})
        assert d.photos_image_override() == (False, None), bad
        assert d.errors and d.errors[-1]["service"] == "photos"
    print("  [OK] pins accepted, floating tags refused")


def run_tests():
    SetupApiHandler.token = TEST_TOKEN
    server = ThreadingHTTPServer(("127.0.0.1", PORT), SetupApiHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    time.sleep(0.5)

    try:
        print("Testing GET /api/health (public)...")
        status, data = request("/api/health", auth=False)
        assert status == 200 and data["status"] == "healthy", data

        print("Testing token enforcement: GET /api/probe without token must be 401...")
        try:
            request("/api/probe", auth=False)
            raise AssertionError("expected HTTP 401 without token")
        except urllib.error.HTTPError as e:
            assert e.code == 401, f"expected 401, got {e.code}"

        print("Testing token enforcement: wrong token must be 401...")
        try:
            req = urllib.request.Request(BASE + "/api/probe", headers={"Authorization": "Bearer nope"})
            urllib.request.urlopen(req, timeout=10)
            raise AssertionError("expected HTTP 401 with wrong token")
        except urllib.error.HTTPError as e:
            assert e.code == 401

        print("Testing GET /api/probe...")
        status, data = request("/api/probe")
        assert status == 200
        print(" -> CPU:", data["cpu"]["model"])
        print(" -> RAM:", data["ram"]["total_gib"], "GiB")
        print(" -> Active NIC:", data["network"]["active_nic"])
        print(" -> Disks count:", len(data["disks"]))
        assert data["network"]["active_nic"], "active NIC must be detected"

        print("Testing GET /api/ai/context...")
        status, data = request("/api/ai/context")
        assert status == 200 and len(data["prompt"]) > 100

        print("Testing POST /api/verify/hardlink...")
        status, data = request("/api/verify/hardlink", {"path": "."})
        assert status == 200
        print(" -> Hardlink test result:", data)

        print("Testing POST /api/secrets/generate...")
        status, data = request("/api/secrets/generate", {})
        assert status == 200
        for key in ("qbittorrent_pass", "postgres_password", "radarr_api_key"):
            assert len(data[key]) >= 16, key
        print(" -> Generated secrets:", list(data.keys()))

        print("Testing static HTML / CSS / JS (public)...")
        status, html = request("/", auth=False)
        assert status == 200 and "Homelab Blueprint Setup" in html
        status, css = request("/css/setup.css", auth=False)
        assert status == 200 and "--cyan" in css
        status, js = request("/js/setup.js", auth=False)
        assert status == 200 and "Authorization" in js, "wizard JS must send the bearer token"

        print("Testing path traversal is blocked...")
        try:
            request("/../server.py", auth=False)
        except urllib.error.HTTPError as e:
            assert e.code in (403, 404)

        print("Testing POST /api/deploy with dry_run=True...")
        deploy_payload = {
            "mode": "express",
            "dry_run": True,
            "hdd_data": "/mnt/hdd/data",
            "hdd_memories": "/mnt/hdd/Memories",
            "server_ip": "192.168.1.100",
            "enable_static_ip": True,
            "active_nic": "enp3s0",
            "qbittorrent_pass": "testpass123",
            "puid": 1000,
            "pgid": 1000,
            "timezone": "UTC",
            "enabled_services": ["media", "photos", "control_hub"],
        }
        status, deploy_res = request("/api/deploy", deploy_payload)
        assert status == 200
        assert deploy_res["success"] is True, deploy_res.get("errors")
        assert deploy_res["dry_run"] is True
        assert deploy_res["credentials"]["control_hub_token"], "a Control Hub token must be generated"
        assert deploy_res["credentials"]["postgres_password"] not in ("", "postgres"), "no default DB password"
        print(" -> Deployment success:", deploy_res["success"])
        print(" -> Services launched:", deploy_res["services_launched"])
        print(" -> Dashboard URL:", deploy_res["dashboard_url"])

        preview_env = REPO_ROOT / "setup" / "dry_run_preview" / "etc" / "homelab" / "mediaserver.env"
        assert preview_env.exists(), "dry run must render env previews under setup/dry_run_preview/etc/homelab"
        rendered = preview_env.read_text(encoding="utf-8")
        assert "QBITTORRENT_PASS=testpass123" in rendered
        assert "adminadmin" not in rendered

        test_exit_waits_for_netplan_confirm()
        test_photos_image_override()

        print("ALL TESTS PASSED WITH 100% SUCCESS!")
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    run_tests()
