"""Media keys from key files (plan section 9.1), deletes through the app queue (D4) and
download names and counts by health (D6)."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

CH_DIR = Path(__file__).resolve().parent.parent
if str(CH_DIR) not in sys.path:
    sys.path.insert(0, str(CH_DIR))

import config  # noqa: E402
import server  # noqa: E402
from core import telemetry_sampler  # noqa: E402
from widgets import current_downloads  # noqa: E402

H = "ab" * 20


def resp(status=200, payload=None):
    r = mock.Mock(status_code=status)
    r.json.return_value = payload
    r.raise_for_status = mock.Mock(side_effect=None if status < 400 else Exception(f"HTTP {status}"))
    return r


class TestApiKeysFromFiles(unittest.TestCase):
    def test_environment_wins_then_key_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "radarr.key").write_text("from-file\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {"HOMELAB_ETC_DIR": tmp}, clear=False):
                os.environ.pop("RADARR_API_KEY", None)
                self.assertEqual(config._api_key("RADARR_API_KEY", "radarr.key"), "from-file")
                with mock.patch.dict(os.environ, {"RADARR_API_KEY": "from-env"}):
                    self.assertEqual(config._api_key("RADARR_API_KEY", "radarr.key"), "from-env")
                self.assertEqual(config._api_key("SEERR_API_KEY", "seerr.key"), "", "a missing file means not configured")


class TestDeleteThroughApp(unittest.TestCase):
    def setUp(self) -> None:
        self._orig = os.environ.get("CONTROL_HUB_TOKEN")
        os.environ["CONTROL_HUB_TOKEN"] = "delete-test-token"
        self.client = server.create_app().test_client()
        self.headers = {"Authorization": "Bearer delete-test-token"}
        self.qbit_calls = []
        patches = [mock.patch.object(current_downloads, "RADARR_API_KEY", "rk"),
                   mock.patch.object(current_downloads, "RADARR_URL", "http://radarr"),
                   mock.patch.object(current_downloads, "SONARR_API_KEY", "sk"),
                   mock.patch.object(current_downloads, "SONARR_URL", "http://sonarr"),
                   mock.patch.object(current_downloads, "_post_qbit",
                                     side_effect=lambda ep, data: self.qbit_calls.append((ep, data)) or resp(200))]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self) -> None:
        if self._orig is None:
            os.environ.pop("CONTROL_HUB_TOKEN", None)
        else:
            os.environ["CONTROL_HUB_TOKEN"] = self._orig

    def queues(self, radarr=(), sonarr=()):
        def get(url, params=None, headers=None, timeout=None):
            records = radarr if "radarr" in url else sonarr
            return resp(200, {"records": [dict(r) for r in records]})
        return get

    def delete(self, **payload):
        return self.client.post(f"/api/torrents/{H}/action", json=dict(action="delete", **payload), headers=self.headers)

    def test_app_owned_download_is_removed_through_the_queue(self):
        with mock.patch.object(current_downloads.requests, "get", side_effect=self.queues(radarr=[{"id": 5, "downloadId": H.upper()}])), \
                mock.patch.object(current_downloads.requests, "delete", return_value=resp(200)) as rm:
            res = self.delete(delete_files=True)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["via"], "radarr")
        (url,), kw = rm.call_args
        self.assertEqual(url, "http://radarr/api/v3/queue/5")
        self.assertEqual(kw["params"], {"removeFromClient": "true", "blocklist": "true", "skipRedownload": "false"})
        self.assertEqual(self.qbit_calls, [], "never deleted behind the app's back")

    def test_season_pack_is_one_bulk_call_and_blocklist_can_be_skipped(self):
        records = [{"id": i, "downloadId": H.upper()} for i in (21, 22, 23)]
        with mock.patch.object(current_downloads.requests, "get", side_effect=self.queues(sonarr=records)), \
                mock.patch.object(current_downloads.requests, "delete", return_value=resp(200)) as rm:
            res = self.delete(blocklist=False, search=False)
        self.assertEqual(res.get_json()["via"], "sonarr")
        (url,), kw = rm.call_args
        self.assertEqual(url, "http://sonarr/api/v3/queue/bulk")
        self.assertEqual(kw["json"], {"ids": [21, 22, 23]})
        self.assertEqual(kw["params"]["blocklist"], "false")
        self.assertEqual(kw["params"]["skipRedownload"], "true")

    def test_manual_torrent_is_deleted_in_qbittorrent(self):
        with mock.patch.object(current_downloads.requests, "get", side_effect=self.queues()):
            res = self.delete(delete_files=False)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self.qbit_calls, [("/api/v2/torrents/delete", {"hashes": H, "deleteFiles": "false"})])

    def test_app_unreachable_refuses_unless_forced(self):
        with mock.patch.object(current_downloads.requests, "get", side_effect=OSError("connection refused")):
            res = self.delete()
            self.assertEqual(res.status_code, 502)
            self.assertIn("Could not check", res.get_json()["error"])
            self.assertEqual(self.qbit_calls, [])
            res = self.delete(force_client=True)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(self.qbit_calls), 1)


class TestDownloadNamesAndHealth(unittest.TestCase):
    def test_names_decoded_and_stalled_not_counted_active(self):
        torrents = [
            {"name": "Tom &amp; Jerry &#039;Best&#039;", "hash": "1", "state": "downloading", "dlspeed": 900000, "progress": 0.4},
            {"name": "Dead", "hash": "2", "state": "stalledDL", "dlspeed": 0, "progress": 0.04},
            {"name": "Meta", "hash": "3", "state": "metaDL", "dlspeed": 0, "progress": 0},
            {"name": "Done", "hash": "4", "state": "stalledUP", "dlspeed": 0, "progress": 1},
            {"name": "Paused", "hash": "5", "state": "stoppedDL", "dlspeed": 0, "progress": 0.2},
        ]

        def get(url, timeout=None):
            if url.endswith("/transfer/info"):
                return resp(200, {"dl_info_speed": 900000, "up_info_speed": 0, "dht_nodes": 300})
            return resp(200, torrents)

        with mock.patch.object(telemetry_sampler, "QBITTORRENT_URL", "http://qbit"), \
                mock.patch.object(telemetry_sampler.qb_session, "get", side_effect=get):
            out = telemetry_sampler._poll_qbittorrent()
        active, paused, items = out[5], out[6], out[8]
        self.assertEqual(items[0]["name"], "Tom & Jerry 'Best'")
        self.assertEqual([i["health"] for i in items], ["moving", "stalled", "stalled", "seeding", "paused"])
        self.assertEqual((active, paused), (1, 1), "dead and metadata-stuck torrents are not active")


if __name__ == "__main__":
    unittest.main()
