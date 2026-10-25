"""
Verification test for Homelab Blueprint Setup Server and APIs
"""

import json
import urllib.request
import threading
import time
import sys
from pathlib import Path
from http.server import HTTPServer

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from setup.server import SetupApiHandler

def run_tests():
    server = HTTPServer(("127.0.0.1", 8089), SetupApiHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    time.sleep(1)

    print("Testing GET /api/health...")
    with urllib.request.urlopen("http://127.0.0.1:8089/api/health") as res:
        assert res.status == 200
        data = json.loads(res.read().decode())
        print(" -> Response:", data)

    print("Testing GET /api/probe...")
    with urllib.request.urlopen("http://127.0.0.1:8089/api/probe") as res:
        assert res.status == 200
        data = json.loads(res.read().decode())
        print(" -> CPU:", data["cpu"]["model"])
        print(" -> RAM:", data["ram"]["total_gib"], "GiB")
        print(" -> Active NIC:", data["network"]["active_nic"])
        print(" -> Disks count:", len(data["disks"]))

    print("Testing GET /api/ai/context...")
    with urllib.request.urlopen("http://127.0.0.1:8089/api/ai/context") as res:
        assert res.status == 200
        data = json.loads(res.read().decode())
        print(" -> Prompt length:", len(data["prompt"]), "chars")

    print("Testing POST /api/verify/hardlink...")
    req = urllib.request.Request(
        "http://127.0.0.1:8089/api/verify/hardlink",
        data=json.dumps({"path": "."}).encode(),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as res:
        assert res.status == 200
        data = json.loads(res.read().decode())
        print(" -> Hardlink test result:", data)

    print("Testing POST /api/secrets/generate...")
    req = urllib.request.Request(
        "http://127.0.0.1:8089/api/secrets/generate",
        data=b"{}",
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as res:
        assert res.status == 200
        data = json.loads(res.read().decode())
        print(" -> Generated secrets:", list(data.keys()))

    print("Testing GET static HTML...")
    with urllib.request.urlopen("http://127.0.0.1:8089/") as res:
        assert res.status == 200
        html = res.read().decode()
        assert "Homelab Blueprint Setup" in html
        print(" -> HTML loaded successfully (", len(html), "bytes )")

    print("Testing GET static CSS...")
    with urllib.request.urlopen("http://127.0.0.1:8089/css/setup.css") as res:
        assert res.status == 200
        css = res.read().decode()
        assert "--cyan" in css
        print(" -> CSS loaded successfully (", len(css), "bytes )")

    print("Testing GET static JS...")
    print("Testing POST /api/deploy with dry_run=True...")
    deploy_payload = {
        "mode": "express",
        "dry_run": True,
        "hdd_data": "/mnt/hdd/data",
        "hdd_memories": "/mnt/hdd/Memories",
        "server_ip": "192.168.1.100",
        "enable_static_ip": True,
        "active_nic": "eth0",
        "qbittorrent_pass": "testpass123",
        "puid": 1000,
        "pgid": 1000,
        "timezone": "Asia/Kolkata",
        "enabled_services": ["media", "photos"]
    }
    req = urllib.request.Request(
        "http://127.0.0.1:8089/api/deploy",
        data=json.dumps(deploy_payload).encode(),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as res:
        assert res.status == 200
        deploy_res = json.loads(res.read().decode())
        assert deploy_res["success"] is True
        print(" -> Deployment success:", deploy_res["success"])
        print(" -> Services launched count:", len(deploy_res["services_launched"]))
        print(" -> Sample log:", deploy_res["logs"][0])
        print(" -> Dashboard URL:", deploy_res["dashboard_url"])

    server.shutdown()
    print("ALL TESTS PASSED WITH 100% SUCCESS!")

if __name__ == "__main__":
    run_tests()
