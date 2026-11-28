"""
system/helpers/homelab-backup-remote: the root helper behind "Change remote".

It runs as root through sudo with an argument from the dashboard, so its input checks
matter: these tests cover validation, listing, testing and rewriting the files.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HELPER = Path(__file__).resolve().parent.parent / "system" / "helpers" / "homelab-backup-remote"
_loader = importlib.machinery.SourceFileLoader("homelab_backup_remote", str(HELPER))
_spec = importlib.util.spec_from_loader("homelab_backup_remote", _loader)
hbr = importlib.util.module_from_spec(_spec)
_loader.exec_module(hbr)


def done(stdout="", returncode=0, stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


class TestValidation(unittest.TestCase):
    def test_accepts_plain_remotes(self):
        self.assertEqual(hbr.parse_remote("gdrive:")["remote"], "gdrive:")
        self.assertEqual(hbr.parse_remote(" my_drive-2: homelab/backups ")["remote"], "my_drive-2:homelab/backups/")
        self.assertEqual(hbr.parse_remote("b2:bucket")["remote"], "b2:bucket/")

    def test_rejects_anything_else(self):
        for bad in ("", "gdrive", "-o:", "--config=/tmp/x:", "a:../etc", "a:x/../../y", "a:/abs", "a;rm -rf /:",
                    "a:$(id)", "a:`id`", "a:x\ny", "a" * 70 + ":"):
            with self.assertRaises(hbr.Invalid, msg=repr(bad)):
                hbr.parse_remote(bad)


class TestRclone(unittest.TestCase):
    def test_list(self):
        with mock.patch.object(hbr, "rclone", return_value=done("gdrive:   drive\nb2:       b2\n")):
            self.assertEqual(hbr.list_remotes(), [{"name": "gdrive", "type": "drive"}, {"name": "b2", "type": "b2"}])

    def test_unknown_remote_is_refused_before_rclone_touches_it(self):
        with mock.patch.object(hbr, "rclone", return_value=done("gdrive:   drive\n")) as rc:
            with self.assertRaises(hbr.Invalid):
                hbr.test_remote("other:")
        self.assertEqual(rc.call_count, 1)  # only listremotes

    def test_existing_remote_with_folders(self):
        calls = {
            ("listremotes", "--long"): done("gdrive:   drive\n"),
            ("lsd", "gdrive:"): done("  -1 2026-01-01 00:00:00  -1 Memories\n  -1 2026-01-01 00:00:00  -1 Immich_Backup\n"),
            ("lsd", "gdrive:Immich_Backup"): done("  -1 2026-01-01 00:00:00  -1 database\n"),
            ("about", "gdrive:", "--json"): done(json.dumps({"total": 100, "free": 40})),
        }
        with mock.patch.object(hbr, "rclone", side_effect=lambda args, timeout=0: calls[tuple(args)]):
            r = hbr.test_remote("gdrive:")
        self.assertTrue(r["ok"])
        self.assertEqual(r["folders"], {"Memories": True, "Immich_Backup/database": True, "Media_Backup": False})
        self.assertEqual(r["free_bytes"], 40)

    def test_new_folder_on_a_working_remote_is_fine(self):
        calls = {
            ("listremotes", "--long"): done("gdrive:   drive\n"),
            ("lsd", "gdrive:new/"): done("", 3, "ERROR : directory not found"),
            ("lsd", "gdrive:"): done("  -1 2026-01-01 00:00:00  -1 Memories\n"),
            ("about", "gdrive:new/", "--json"): done("", 1),
        }
        with mock.patch.object(hbr, "rclone", side_effect=lambda args, timeout=0: calls[tuple(args)]):
            r = hbr.test_remote("gdrive:new")
        self.assertTrue(r["ok"])
        self.assertFalse(r["folders"]["Memories"], "the root's folders are not the new folder's")

    def test_dead_remote(self):
        calls = {
            ("listremotes", "--long"): done("gdrive:   drive\n"),
            ("lsd", "gdrive:"): done("", 1, "Failed to create file system: couldn't fetch token: invalid_grant"),
        }
        with mock.patch.object(hbr, "rclone", side_effect=lambda args, timeout=0: calls[tuple(args)]):
            r = hbr.test_remote("gdrive:")
        self.assertFalse(r["ok"])
        self.assertIn("invalid_grant", r["error"])


class TestSet(unittest.TestCase):
    def test_rewrites_every_file_and_keeps_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            cron1, cron2 = d / "immich-backup", d / "media-backup"
            env, cfg = d / "control-hub.env", d / "config.json"
            cron1.write_text("BACKUP_LOCAL=/x\nGDRIVE_REMOTE=old:\n0 22 * * * root /usr/local/sbin/x\n", encoding="utf-8")
            cron2.write_text("GDRIVE_REMOTE=old:\n30 21 * * * root y\n", encoding="utf-8")
            env.write_text("A=1\nGDRIVE_REMOTE=old:\nTZ=UTC\n", encoding="utf-8")
            cfg.write_text(json.dumps({"gdrive_remote": "old:", "hdd_data": "/mnt"}), encoding="utf-8")
            os.chmod(env, 0o640)
            tested = {"ok": True, "remote": "new:homelab/", "folders": {}}
            with mock.patch.object(hbr, "CRON_FILES", [cron1, cron2]), \
                 mock.patch.object(hbr, "ENV_FILES", [env, d / "missing.env"]), \
                 mock.patch.object(hbr, "CONFIG_JSON", cfg), \
                 mock.patch.object(hbr, "test_remote", return_value=tested):
                out = hbr.set_remote("new:homelab")
                self.assertEqual(hbr.current_remote(), "new:homelab/")
            self.assertTrue(out["ok"])
            self.assertEqual(len(out["changed"]), 4)
            self.assertIn("GDRIVE_REMOTE=new:homelab/\n0 22", cron1.read_text(encoding="utf-8"))
            self.assertEqual(env.read_text(encoding="utf-8"), "A=1\nGDRIVE_REMOTE=new:homelab/\nTZ=UTC\n")
            self.assertEqual(json.loads(cfg.read_text(encoding="utf-8")), {"gdrive_remote": "new:homelab/", "hdd_data": "/mnt"})
            if os.name != "nt":
                self.assertEqual(oct(env.stat().st_mode & 0o777), oct(0o640))

    def test_failed_test_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            cron = Path(tmp) / "immich-backup"
            cron.write_text("GDRIVE_REMOTE=old:\n", encoding="utf-8")
            with mock.patch.object(hbr, "CRON_FILES", [cron]), \
                 mock.patch.object(hbr, "test_remote", return_value={"ok": False, "error": "no answer"}):
                out = hbr.set_remote("dead:")
            self.assertFalse(out["ok"])
            self.assertEqual(cron.read_text(encoding="utf-8"), "GDRIVE_REMOTE=old:\n")

    def test_cli_rejects_bad_usage(self):
        self.assertEqual(hbr.main(["x"]), 64)
        self.assertEqual(hbr.main(["x", "set"]), 64)
        self.assertEqual(hbr.main(["x", "rm", "y"]), 64)


if __name__ == "__main__":
    unittest.main()
