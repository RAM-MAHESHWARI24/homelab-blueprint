"""TV names: detected model, user nicknames and honest status for offline TVs."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import tv_updater  # noqa: E402

PROFILES = [
    {"id": "living_room_tv", "name": "Living Room TV (example)", "default_ip": "192.168.1.34", "port": 5555,
     "match_models": ["shield", "mibox4"]},
    {"id": "bedroom_tv", "name": "Bedroom TV (example)", "default_ip": "192.168.1.39", "port": 5555,
     "match_models": ["mitv-axfr0"]},
]


class _Isolated(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        (d / "incoming").mkdir()
        self.patches = [
            mock.patch.object(tv_updater, "TARGET_PROFILES", PROFILES),
            mock.patch.object(tv_updater, "NICKNAMES_FILE", d / "nicknames.json"),
            mock.patch.object(tv_updater, "DEVICE_INFO_FILE", d / "device_info.json"),
            mock.patch.object(tv_updater, "STATE_FILE", d / "state.json"),
            mock.patch.object(tv_updater, "DEVICES_CACHE_FILE", d / "devices_cache.json"),
            mock.patch.object(tv_updater, "INCOMING_DIR", d / "incoming"),
        ]
        for p in self.patches:
            p.start()
        self.dir = d

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()


class TestNicknames(_Isolated):
    def test_set_clear_and_validate(self):
        self.assertEqual(tv_updater.set_nickname("living_room_tv", "  Living   room  "), "Living room")
        self.assertEqual(json.loads((self.dir / "nicknames.json").read_text()), {"living_room_tv": "Living room"})
        self.assertIsNone(tv_updater.set_nickname("living_room_tv", ""))
        self.assertEqual(tv_updater.load_nicknames(), {})
        with self.assertRaises(KeyError):
            tv_updater.set_nickname("garage_tv", "x")
        with self.assertRaises(ValueError):
            tv_updater.set_nickname("living_room_tv", "x" * 41)
        with self.assertRaises(ValueError):
            tv_updater.set_nickname("living_room_tv", "bad\x07name")


class TestDetectedModel(unittest.TestCase):
    def test_probe_parses_getprop_and_device_name(self):
        out = "Xiaomi\nMIBOX4\noneday\n9\n28\nMi Box\n"
        with mock.patch.object(tv_updater, "adb_cmd", return_value=SimpleNamespace(stdout=out, returncode=0)):
            info = tv_updater.probe_device_info("192.168.1.34")
        self.assertEqual(info, {"manufacturer": "Xiaomi", "model": "MIBOX4", "device": "oneday",
                                "android": "9", "sdk": "28", "device_name": "Mi Box"})
        with mock.patch.object(tv_updater, "adb_cmd", return_value=SimpleNamespace(stdout="error: device unauthorized\n", returncode=1)):
            self.assertEqual(tv_updater.probe_device_info("192.168.1.34"), {})

    def test_model_label(self):
        self.assertEqual(tv_updater.model_label({"manufacturer": "Xiaomi", "model": "MIBOX4"}), "Xiaomi MIBOX4")
        self.assertEqual(tv_updater.model_label({"manufacturer": "xiaomi", "model": "MiTV-AXFR0"}), "Xiaomi MiTV-AXFR0")
        self.assertEqual(tv_updater.model_label({"manufacturer": "Sony", "model": "Sony BRAVIA 4K"}), "Sony BRAVIA 4K")
        self.assertIsNone(tv_updater.model_label({}))


class TestTelemetryNames(_Isolated):
    def test_online_tv_gets_detected_model_and_offline_tv_is_honest(self):
        (self.dir / "state.json").write_text(json.dumps({
            "upstream_apps": {"org.smarttube.stable": {"version_code": 2470, "version_name": "32.80"}},
            "devices": {"bedroom_tv": {"installed": {"org.smarttube.stable": 2470}}},
        }))
        tv_updater.set_nickname("bedroom_tv", "Bedroom")
        info = {"manufacturer": "Xiaomi", "model": "MIBOX4", "device": "oneday", "android": "9", "sdk": "28"}
        with mock.patch.object(tv_updater, "is_port_open", side_effect=lambda ip, *a, **k: ip.endswith(".34")), \
             mock.patch.object(tv_updater, "probe_device_info", return_value=info) as probe, \
             mock.patch.object(tv_updater, "get_foreground_package", return_value=""), \
             mock.patch.object(tv_updater, "is_media_playing", return_value=(False, "")), \
             mock.patch.object(tv_updater, "get_installed_version_code", return_value=-1), \
             mock.patch.object(tv_updater, "get_installed_version_name", return_value=""):
            data = tv_updater.get_cluster_telemetry(fast_probe=True)
            tv_updater.get_cluster_telemetry(fast_probe=True)
        self.assertEqual(probe.call_count, 1, "device info is cached, not probed on every poll")
        living, bedroom = data["devices"]
        self.assertEqual(living["name"], "Xiaomi MIBOX4")
        self.assertEqual(living["model"], "MIBOX4")
        self.assertIsNone(living["nickname"])
        self.assertEqual(living["details"]["android"], "9")
        self.assertIsNotNone(living["details"]["last_seen"])
        self.assertEqual(bedroom["name"], "Bedroom")
        self.assertIsNone(bedroom["model"], "never seen: no invented model")
        st = [a for a in bedroom["apps"] if a["package"] == "org.smarttube.stable"][0]
        self.assertTrue(st["status_text"].endswith("when last seen"))
        saved = json.loads((self.dir / "device_info.json").read_text())
        self.assertEqual(saved["living_room_tv"]["model"], "MIBOX4")


if __name__ == "__main__":
    unittest.main()
