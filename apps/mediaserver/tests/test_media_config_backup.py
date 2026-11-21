"""Tests for scripts/media_config_backup.py: settings, what is copied, retention, history."""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import media_config_backup as mcb  # noqa: E402


class TestSettings(unittest.TestCase):
    def test_env_wins_and_cron_file_fills_the_rest(self):
        with tempfile.TemporaryDirectory() as tmp:
            cron = Path(tmp) / "media-backup"
            cron.write_text("# comment\nMEDIA_APPDATA=/srv/x\nGDRIVE_REMOTE=drive\nKEEP_REMOTE=7\n"
                            "30 21 * * * root /usr/bin/python3 /opt/x.py\n", encoding="utf-8")
            s = mcb.load_settings({"MEDIA_BACKUP_CRON_FILE": str(cron), "KEEP_REMOTE": "9"})
        self.assertEqual(s["appdata"], "/srv/x")
        self.assertEqual(s["remote"], "drive/")
        self.assertEqual(s["remote_dir"], "drive/Media_Backup")
        self.assertEqual(s["keep_remote"], 9)
        self.assertEqual(s["keep_local"], 3)
        self.assertFalse(s["jellyfin_metadata"])

    def test_remote_with_colon_is_kept(self):
        s = mcb.load_settings({"MEDIA_BACKUP_CRON_FILE": "/nonexistent", "GDRIVE_REMOTE": "gdrive:"})
        self.assertEqual(s["remote_dir"], "gdrive:Media_Backup")


class TestSnapshot(unittest.TestCase):
    def build_tree(self, root: Path) -> None:
        files = {
            "sonarr/config.xml": "<Config/>",
            "sonarr/logs/sonarr.txt": "log",
            "sonarr/logs.db": "x",
            "sonarr/MediaCover/1/poster.jpg": "img",
            "sonarr/Backups/scheduled/a.zip": "zip",
            "radarr/radarr.txt.1": "rotated",
            "qbittorrent/qBittorrent/qBittorrent.conf": "[Prefs]",
            "qbittorrent/qBittorrent/BT_backup/abc.fastresume": "x",
            "qbittorrent/qBittorrent/lockfile": "",
            "jellyfin/system.xml": "<x/>",
            "jellyfin/cache/images/a.jpg": "img",
            "jellyfin/data/metadata/library/a.jpg": "img",
        }
        for rel, text in files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        # A live database in WAL mode with an uncheckpointed write.
        db = root / "sonarr" / "sonarr.db"
        self.live = sqlite3.connect(str(db))
        self.live.execute("PRAGMA journal_mode=WAL")
        self.live.execute("CREATE TABLE Series (id INTEGER PRIMARY KEY, title TEXT)")
        self.live.executemany("INSERT INTO Series (title) VALUES (?)", [("A",), ("B",), ("C",)])
        self.live.commit()

    def test_copies_settings_and_skips_rebuildable_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, staging = Path(tmp) / "appdata", Path(tmp) / "staging"
            self.build_tree(root)
            try:
                stats = mcb.snapshot(root, staging, jellyfin_metadata=False)
            finally:
                self.live.close()
            copied = {str(p.relative_to(staging)).replace("\\", "/") for p in staging.rglob("*") if p.is_file()}
            self.assertEqual(copied, {
                "sonarr/config.xml", "sonarr/sonarr.db",
                "qbittorrent/qBittorrent/qBittorrent.conf", "qbittorrent/qBittorrent/BT_backup/abc.fastresume",
                "jellyfin/system.xml",
            })
            self.assertEqual(stats["databases"], 1)
            con = sqlite3.connect(str(staging / "sonarr" / "sonarr.db"))
            self.assertEqual(con.execute("SELECT count(*) FROM Series").fetchone()[0], 3, "WAL content included")
            self.assertEqual(con.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            con.close()

    def test_jellyfin_metadata_can_be_included(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, staging = Path(tmp) / "appdata", Path(tmp) / "staging"
            self.build_tree(root)
            self.live.close()
            mcb.snapshot(root, staging, jellyfin_metadata=True)
            self.assertTrue((staging / "jellyfin" / "data" / "metadata" / "library" / "a.jpg").exists())
            self.assertFalse((staging / "jellyfin" / "cache").exists() and any((staging / "jellyfin" / "cache").rglob("*.jpg")))


class TestRetention(unittest.TestCase):
    def names(self, start, days):
        return [(start + timedelta(days=i)).strftime("media_config_%Y%m%d_213001.tar.zst") for i in range(days)]

    def test_newest_plus_monthlies_and_foreign_files_ignored(self):
        names = self.names(datetime(2026, 9, 26), 56) + ["notes.txt", "media_config_manual.tar.zst"]
        plan = mcb.plan_retention(names, keep=14, monthly=12)
        self.assertEqual(len(plan["keep"]), 17)
        self.assertIn("media_config_20260926_213001.tar.zst", plan["keep"])
        self.assertIn("media_config_20261001_213001.tar.zst", plan["keep"])
        self.assertNotIn("notes.txt", plan["delete"])
        self.assertNotIn("media_config_manual.tar.zst", plan["delete"])

    def test_local_keep_and_protect(self):
        names = self.names(datetime(2026, 11, 18), 4)
        self.assertEqual(mcb.plan_retention(names, 3, 0)["delete"], [names[0]])
        self.assertEqual(mcb.plan_retention(names, 3, 0, protect=names[0])["delete"], [])


class TestStatus(unittest.TestCase):
    def test_finish_records_history_and_last_good(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "status.json"
            s = mcb.Status(path, "drive:")
            s.data.update(dump_file="media_config_x.tar.zst", dump_bytes=1234, snapshot={"files": 7})
            s.finish(True, "ok")
            d = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(d["status"], "synced")
            self.assertEqual(d["last_good_at"], d["completed_at"])
            self.assertEqual(d["history"][0]["files"], 7)
            s2 = mcb.Status(path, "drive:")
            s2.check("remote", False, "did not answer")
            s2.finish(False, "Pre-flight: the remote did not answer")
            d = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual([h["outcome"] for h in d["history"]], ["error", "synced"])
            self.assertEqual(d["last_good_at"], d["history"][1]["completed_at"])
            self.assertFalse(d["preflight"]["ok"])


if __name__ == "__main__":
    unittest.main()
