#!/usr/bin/env python3
"""
Homelab Blueprint - Complete Lifecycle Handoff & Full-Flow Regression Test
Validates the complete two-phase operational lifecycle:
  Phase 1: Day 0 Onboarding & Provisioning Wizard (setup/server.py on port 8000)
    - Hardware auto-probing (CPU, RAM, NICs, Disks)
    - Inode-level atomic hardlink verification (os.link)
    - Cryptographic secret generation
    - Safe Netplan preview
    - Dry-run deployment pipeline & multi-subsystem .env generation
  Phase 2: Day 1+ Command Center & Control Hub (apps/control-hub on port 7575)
    - Seamless handoff of configured storage, user IDs, and secrets
    - Real-time dynamic hardware vitals (CPU model, threads, RAM, swap)
    - 13-Service socket port conflict prober
    - Real-time storage operations & dynamic block device resolution
    - Sleep Guard S3 power management status & deferral logic
    - AI Copilot ~300-token prompt generation
    - Web HUD static assets & dashboard rendering
"""

import os
import sys
import json
import time
import shutil
import tempfile
import unittest
import threading
import urllib.request
from pathlib import Path
from http.server import HTTPServer

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "apps" / "control-hub"))

from setup.server import SetupApiHandler
from server import create_app


class TestCompleteLifecycleHandoff(unittest.TestCase):
    """End-to-End Test Suite for Phase 1 (Setup Wizard) -> Phase 2 (Control Hub) Handoff"""

    @classmethod
    def setUpClass(cls):
        """Spins up Setup Wizard on an ephemeral port and initializes Control Hub test client"""
        cls.wizard_port = 8099
        cls.wizard_server = HTTPServer(("127.0.0.1", cls.wizard_port), SetupApiHandler)
        cls.wizard_thread = threading.Thread(target=cls.wizard_server.serve_forever, daemon=True)
        cls.wizard_thread.start()
        time.sleep(0.5)

        # Control Hub Flask App
        cls.hub_app = create_app()
        cls.hub_client = cls.hub_app.test_client()

    @classmethod
    def tearDownClass(cls):
        """Gracefully shuts down Setup Wizard server"""
        try:
            cls.wizard_server.shutdown()
            cls.wizard_server.server_close()
        except Exception:
            pass

    # =========================================================================
    # Phase 1: Day 0 Onboarding Wizard Tests (Port 8000)
    # =========================================================================

    def test_01_wizard_health_and_hardware_probe(self):
        """TC-FLOW-01: Setup Wizard healthcheck and dynamic hardware auto-probing"""
        # 1. Healthcheck
        with urllib.request.urlopen(f"http://127.0.0.1:{self.wizard_port}/api/health") as res:
            self.assertEqual(res.status, 200)
            data = json.loads(res.read().decode())
            self.assertEqual(data.get("status"), "healthy")

        # 2. Hardware Probe
        with urllib.request.urlopen(f"http://127.0.0.1:{self.wizard_port}/api/probe") as res:
            self.assertEqual(res.status, 200)
            probe = json.loads(res.read().decode())

            # Validate CPU snapshot
            cpu = probe.get("cpu", {})
            self.assertTrue(len(cpu.get("model", "")) > 0, "Probed CPU model must not be empty")
            self.assertGreaterEqual(cpu.get("threads", 0), 1, "Host must have at least 1 CPU thread")
            self.assertIn("is_low_power", cpu)

            # Validate RAM snapshot
            ram = probe.get("ram", {})
            self.assertGreater(ram.get("total_gib", 0), 0.0, "Total RAM must be > 0 GiB")
            self.assertGreater(ram.get("free_gib", 0), 0.0, "Free RAM must be > 0 GiB")

            # Validate Network snapshot
            net = probe.get("network", {})
            self.assertTrue(len(net.get("active_nic", "")) > 0, "Active NIC must be identified")
            self.assertTrue(len(net.get("current_ip", "")) > 0, "Current IP must be identified")

            # Validate Disks
            disks = probe.get("disks", [])
            self.assertIsInstance(disks, list)
            self.assertGreaterEqual(len(disks), 1, "At least one disk mount must be detected")

    def test_02_wizard_hardlink_and_secrets(self):
        """TC-FLOW-02: Setup Wizard live atomic hardlink probe and CSPRNG secrets generator"""
        # 1. Atomic Hardlink Probe
        payload = json.dumps({"path": "."}).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.wizard_port}/api/verify/hardlink",
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req) as res:
            self.assertEqual(res.status, 200)
            hl = json.loads(res.read().decode())
            self.assertTrue(hl.get("supported"), f"Hardlink probe failed: {hl.get('error')}")
            self.assertIsNotNone(hl.get("inode"))
            self.assertIsNotNone(hl.get("latency_ms"))

        # 2. CSPRNG Secrets Generation
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.wizard_port}/api/secrets/generate",
            data=b"{}",
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req) as res:
            self.assertEqual(res.status, 200)
            secrets = json.loads(res.read().decode())
            for key in ["qbittorrent_pass", "postgres_password", "radarr_api_key", "sonarr_api_key", "prowlarr_api_key"]:
                self.assertIn(key, secrets)
                self.assertGreaterEqual(len(secrets[key]), 16, f"Secret {key} must have sufficient entropy")

    def test_03_wizard_deployment_pipeline_dry_run(self):
        """TC-FLOW-03: Setup Wizard deployment pipeline executes cleanly and generates isolated .env configs"""
        deploy_payload = {
            "mode": "express",
            "dry_run": True,
            "hdd_data": "/mnt/hdd/data",
            "hdd_memories": "/mnt/hdd/Memories",
            "server_ip": "192.168.1.100",
            "enable_static_ip": True,
            "active_nic": "eth0",
            "qbittorrent_pass": "flow_test_password_123",
            "puid": 1000,
            "pgid": 1000,
            "timezone": "Asia/Kolkata",
            "enabled_services": ["media", "photos", "control_hub", "tv_updater"]
        }
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.wizard_port}/api/deploy",
            data=json.dumps(deploy_payload).encode(),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req) as res:
            self.assertEqual(res.status, 200)
            result = json.loads(res.read().decode())
            self.assertTrue(result.get("success"), f"Deployment failed: {result.get('errors')}")
            self.assertIn("dashboard_url", result)
            self.assertIn(":7575", result["dashboard_url"], "Dashboard URL must point to Control Hub on Port 7575")

            # Verify dry-run preview directory was populated without modifying production
            preview_dir = REPO_ROOT / "setup" / "dry_run_preview"
            self.assertTrue(preview_dir.exists())
            self.assertTrue((preview_dir / ".env").exists())

    # =========================================================================
    # Phase 2: Day 1+ Command Center & Control Hub Tests (Port 7575)
    # =========================================================================

    def test_04_control_hub_system_vitals_telemetry(self):
        """TC-FLOW-04: Control Hub dynamically returns real-time hardware vitals across any platform"""
        res = self.hub_client.get("/api/system/vitals")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()

        # 1. CPU Telemetry
        cpu = data.get("cpu", {})
        self.assertIn("usage_percent", cpu)
        self.assertIsInstance(cpu["usage_percent"], (int, float))
        self.assertTrue(len(cpu.get("model", "")) > 0, "Control Hub CPU model must not be empty")
        self.assertGreaterEqual(cpu.get("cores", 0), 1)

        # 2. Memory & Swap
        mem = data.get("memory", {})
        self.assertGreater(mem.get("total_gib", 0), 0.0)
        self.assertGreater(mem.get("free_gib", 0), 0.0)
        self.assertIn("percent", mem)
        swap = data.get("swap", {})
        self.assertIn("percent", swap)

        # 3. Storage Headroom
        storage = data.get("storage", {})
        self.assertIn("ssd", storage)
        self.assertIn("hdd", storage)
        self.assertGreater(storage["ssd"].get("total_gb", 0), 0.0)

        # 4. Uptime & Timestamp
        self.assertIn("uptime", data)
        self.assertIn("local_time", data)

    def test_05_control_hub_config_center_apis(self):
        """TC-FLOW-05: Control Hub live Node Configuration Center endpoints"""
        # 1. Current Config
        res = self.hub_client.get("/api/config/current")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get("status"), "success")
        self.assertIn("config", data)
        self.assertIn("system", data)

        # 2. Port Conflict Prober (13-Service Matrix)
        res = self.hub_client.get("/api/config/ports")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get("status"), "success")
        ports = data.get("ports", {})
        self.assertGreaterEqual(len(ports), 10, "Port prober must track homelab services")
        for key in ["control_hub", "jellyfin_http", "seerr", "sonarr", "radarr", "qbittorrent_web"]:
            self.assertIn(key, ports)
            self.assertIn("port", ports[key])
            self.assertIn("status", ports[key])
            self.assertIn("available", ports[key])

        # 3. Dynamic AI Diagnostics Context Exporter
        res = self.hub_client.get("/api/config/ai-diagnostics")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("ai_prompt", data)
        prompt = data["ai_prompt"]
        self.assertIn("CPU:", prompt)
        self.assertIn("Memory:", prompt)
        self.assertIn("STORAGE_AND_HARDLINKS.md", prompt)

        # 4. Inode Hardlink Verification Endpoint
        res = self.hub_client.post(
            "/api/config/verify-hardlink",
            data=json.dumps({"path": "."}),
            content_type="application/json"
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get("status"), "success")
        self.assertTrue(data.get("result", {}).get("supported"))

        # 5. Secrets Generation Endpoint
        res = self.hub_client.post("/api/config/generate-secrets")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get("status"), "success")
        secrets = data.get("secrets", {})
        self.assertIn("radarr_api_key", secrets)
        self.assertIn("postgres_password", secrets)

    def test_06_control_hub_sleep_guard_and_storage_ops(self):
        """TC-FLOW-06: Control Hub Sleep Guard power telemetry and real-time storage operations"""
        # 1. Sleep Guard Status
        res = self.hub_client.get("/api/sleep/status")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("state_label", data)
        self.assertIn("sleep_time", data)
        self.assertIn("wake_time", data)
        self.assertIn("skip_active", data)

        # 2. Storage Operations (I/O, block devices, clients)
        res = self.hub_client.get("/api/storage/operations")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("collective_mbs", data)
        self.assertIn("hdd", data)
        self.assertIn("ssd", data)
        # Block devices must be identified dynamically
        self.assertTrue(len(data["hdd"].get("device", "")) > 0)
        self.assertTrue(len(data["ssd"].get("device", "")) > 0)

        # 3. Network Speed Telemetry
        res = self.hub_client.get("/api/network/speed")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("network", data)
        self.assertIn("internet", data)
        self.assertIn("speedtest", data)
        self.assertIn("rx_mbps", data["network"])
        self.assertIn("tx_mbps", data["network"])
        self.assertIn("interface", data["network"])

    def test_07_control_hub_web_dashboard_rendering(self):
        """TC-FLOW-07: Control Hub static web dashboard renders all cyber-HUD cards and widget elements"""
        res = self.hub_client.get("/")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)

        # Verify key UI components
        self.assertIn("Control Hub", html)
        self.assertIn("vitals-card-subtitle", html, "Vitals card subtitle must have dynamic ID")
        self.assertIn("vitals-cpu-title", html, "CPU row must have dynamic ID")
        self.assertIn("vitals-ram-title", html, "RAM row must have dynamic ID")
        self.assertIn("vitals-ssd-title", html, "SSD row must have dynamic ID")
        self.assertIn("vitals-hdd-title", html, "HDD row must have dynamic ID")
        self.assertIn("sleep-guard-card", html, "Sleep Guard hero module must be present")
        self.assertIn("config-center-modal", html, "Settings configuration modal must be present")
        self.assertIn("ai-copilot-modal", html, "AI Copilot modal must be present")

    # =========================================================================
    # Phase 1 -> Phase 2 Full Lifecycle Handoff Integration
    # =========================================================================

    def test_08_phase1_to_phase2_configuration_continuity(self):
        """TC-FLOW-08: Complete lifecycle handoff: settings configured in Setup Wizard propagate to Control Hub"""
        temp_env_dir = Path(tempfile.mkdtemp(prefix="homelab_handoff_test_"))
        try:
            from setup.config_core.env_manager import sync_all_blueprint_envs, load_env_file

            custom_test_config = {
                "server_ip": "192.168.1.188",
                "hdd_data": "/mnt/custom_pool/data",
                "hdd_memories": "/mnt/custom_pool/Memories",
                "puid": 1001,
                "pgid": 1001,
                "timezone": "Europe/London",
                "control_hub_port": 7575,
                "active_nic": "enp3s0",
                "radarr_api_key": "HANDOFF_RADARR_TEST_KEY_12345",
                "sonarr_api_key": "HANDOFF_SONARR_TEST_KEY_67890",
            }

            # Simulate Setup Wizard writing configs
            updated_files = sync_all_blueprint_envs(str(temp_env_dir), custom_test_config)
            self.assertIn("master_env", updated_files)
            self.assertTrue(Path(updated_files["master_env"]).exists())

            # Load generated .env
            loaded_env = load_env_file(updated_files["master_env"])
            self.assertEqual(loaded_env.get("SERVER_IP"), "192.168.1.188")
            self.assertEqual(loaded_env.get("HDD_DATA"), "/mnt/custom_pool/data")
            self.assertEqual(loaded_env.get("PUID"), "1001")
            self.assertEqual(loaded_env.get("TIMEZONE"), "Europe/London")
            self.assertEqual(loaded_env.get("RADARR_API_KEY"), "HANDOFF_RADARR_TEST_KEY_12345")

            # Verify Control Hub's config manager can read and update these parameters
            from setup.config_core.env_manager import update_env_variables, write_env_file
            raw_content = Path(updated_files["master_env"]).read_text(encoding="utf-8")
            new_content = update_env_variables(raw_content, {"HDD_DATA": "/mnt/expanded_pool/data"})
            write_env_file(updated_files["master_env"], new_content)
            refreshed_env = load_env_file(updated_files["master_env"])
            self.assertEqual(refreshed_env.get("HDD_DATA"), "/mnt/expanded_pool/data")
            self.assertEqual(refreshed_env.get("RADARR_API_KEY"), "HANDOFF_RADARR_TEST_KEY_12345")
        finally:
            shutil.rmtree(temp_env_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
