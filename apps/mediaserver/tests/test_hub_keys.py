"""`wire_arr.py hub-keys`: the media apps' API keys for the Control Hub (plan section 9.1)."""

import argparse
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import wire_arr  # noqa: E402


def config_dir(root: Path, seerr_dir="seerr"):
    for app, key in (("radarr", "r" * 32), ("sonarr", "s" * 32)):
        (root / app).mkdir(parents=True)
        (root / app / "config.xml").write_text(f"<Config><ApiKey>{key}</ApiKey></Config>", encoding="utf-8")
    (root / seerr_dir).mkdir()
    (root / seerr_dir / "settings.json").write_text(json.dumps({"main": {"apiKey": "seerr-key"}}), encoding="utf-8")


def args(cfg, out, admin_pass=""):
    return argparse.Namespace(config_dir=str(cfg), out_dir=str(out), host="127.0.0.1", admin_user="admin",
                              admin_pass=admin_pass, key_group="", retries=1, json=False)


class TestHubKeys(unittest.TestCase):
    def setUp(self):
        wire_arr.report.update({"steps": [], "errors": [], "warnings": []})
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_writes_key_files_without_jellyfin(self):
        config_dir(self.root / "cfg")
        rc = wire_arr.cmd_hub_keys(args(self.root / "cfg", self.root / "etc"))
        self.assertEqual(rc, 0, wire_arr.report["errors"])
        etc = self.root / "etc"
        self.assertEqual((etc / "radarr.key").read_text(encoding="utf-8").strip(), "r" * 32)
        self.assertEqual((etc / "seerr.key").read_text(encoding="utf-8").strip(), "seerr-key")
        self.assertFalse((etc / "jellyfin.key").exists())
        if os.name == "posix":
            self.assertEqual((etc / "sonarr.key").stat().st_mode & 0o777, 0o640)

    def test_older_jellyseerr_folder(self):
        config_dir(self.root / "cfg", seerr_dir="jellyseerr")
        self.assertEqual(wire_arr.seerr_api_key(self.root / "cfg"), "seerr-key")

    def test_missing_radarr_key_fails(self):
        (self.root / "cfg").mkdir()
        self.assertEqual(wire_arr.cmd_hub_keys(args(self.root / "cfg", self.root / "etc")), 1)

    def test_jellyfin_key_created_once_then_reused(self):
        config_dir(self.root / "cfg")
        keys = []
        calls = []

        def fake_http(url, method="GET", data=None, headers=None, timeout=20):
            calls.append((method, url.split("8096")[-1]))
            if url.endswith("/Users/AuthenticateByName"):
                return 200, json.dumps({"AccessToken": "session"}), {}
            if url.endswith("/Auth/Keys") and method == "GET":
                return 200, json.dumps({"Items": [{"AppName": wire_arr.HUB_KEY_APP, "AccessToken": "jf-key"}] if keys else []}), {}
            if "/Auth/Keys?app=" in url and method == "POST":
                keys.append(1)
                return 204, "", {}
            return 404, "", {}

        with mock.patch.object(wire_arr, "http", side_effect=fake_http):
            self.assertEqual(wire_arr.cmd_hub_keys(args(self.root / "cfg", self.root / "etc", admin_pass="pw")), 0)
            self.assertEqual((self.root / "etc" / "jellyfin.key").read_text(encoding="utf-8").strip(), "jf-key")
            self.assertEqual(sum(1 for m, u in calls if m == "POST" and "/Auth/Keys" in u), 1)
            calls.clear()
            wire_arr.cmd_hub_keys(args(self.root / "cfg", self.root / "etc", admin_pass="pw"))
            self.assertFalse(any(m == "POST" and "/Auth/Keys" in u for m, u in calls), "an existing key is reused")


if __name__ == "__main__":
    unittest.main()
