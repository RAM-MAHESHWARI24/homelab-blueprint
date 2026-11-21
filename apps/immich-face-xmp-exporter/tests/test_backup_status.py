"""Tests for scripts/backup_status.py: retention, rclone stats parsing and status.json history."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import backup_status  # noqa: E402


def nightly(start: datetime, days: int) -> list:
    return [(start + timedelta(days=i)).strftime("immich_db_%Y%m%d_220001.sql.gz") for i in range(days)]


class TestRetention(unittest.TestCase):
    def test_keeps_newest_and_first_of_each_month(self):
        names = nightly(datetime(2026, 9, 26), 56) + ["immich_db_backup_pre_noodle.sql.gz"]
        plan = backup_status.plan_retention(names, keep=14, monthly=12)
        kept = set(plan["keep"])
        self.assertEqual(len([n for n in kept if n >= "immich_db_20261107"]), 14)
        # First dump of September, October and November survive as monthlies.
        for first in ("immich_db_20260926_220001.sql.gz", "immich_db_20261001_220001.sql.gz", "immich_db_20261101_220001.sql.gz"):
            self.assertIn(first, kept)
        self.assertEqual(len(kept), 17)
        self.assertEqual(len(plan["delete"]), 56 - 17)
        # A file that is not a nightly dump is never kept-or-deleted: it is ignored.
        self.assertNotIn("immich_db_backup_pre_noodle.sql.gz", plan["delete"])

    def test_monthly_limit_and_protect(self):
        names = nightly(datetime(2025, 1, 1), 500)  # 2025-01-01 .. 2026-05-15
        plan = backup_status.plan_retention(names, keep=3, monthly=2, protect=names[0])
        self.assertEqual(sorted(plan["keep"]), sorted([
            "immich_db_20250101_220001.sql.gz",  # protected
            "immich_db_20260401_220001.sql.gz",  # first of April
            "immich_db_20260501_220001.sql.gz",  # first of May
            "immich_db_20260513_220001.sql.gz", "immich_db_20260514_220001.sql.gz", "immich_db_20260515_220001.sql.gz",
        ]))
        self.assertEqual(len(plan["delete"]), 500 - 6)

    def test_nothing_deleted_below_limit_and_local_mode(self):
        names = nightly(datetime(2026, 11, 18), 3)
        self.assertEqual(backup_status.plan_retention(names, keep=3, monthly=0)["delete"], [])
        four = nightly(datetime(2026, 11, 18), 4)
        self.assertEqual(backup_status.plan_retention(four, keep=3, monthly=0)["delete"], [four[0]])

    def test_cli_writes_next_delete_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            names_file = Path(tmp) / "names.txt"
            names_file.write_text("\n".join(nightly(datetime(2026, 11, 7), 14)) + "\n", encoding="utf-8")
            out = Path(tmp) / "r.json"
            backup_status.main(["retention", "--names-file", str(names_file), "--keep", "14", "--monthly", "0", "--json-out", str(out)])
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(data["delete"], [])
            self.assertEqual(data["next_delete"], ["immich_db_20261107_220001.sql.gz"])


class TestStats(unittest.TestCase):
    def test_parses_last_block(self):
        text = (
            "2026/11/21 22:01:00 NOTICE: \n"
            "Transferred:   \t   10 MiB / 340 MiB, 3%, 5 MiB/s, ETA 1m\n"
            "Transferred:            0 / 1, 0%\n"
            "2026/11/21 22:02:10 NOTICE: \n"
            "Transferred:   \t  339.773 MiB / 339.773 MiB, 100%, 5.1 MiB/s, ETA 0s\n"
            "Checks:              1234 / 1234, 100%\n"
            "Deleted:                2 (files), 0 (dirs)\n"
            "Transferred:            1 / 1, 100%\n"
            "Elapsed time:      1m10.2s\n"
        )
        stats = backup_status.parse_rclone_stats(text)
        self.assertEqual(stats["files"], 1)
        self.assertEqual(stats["checks"], 1234)
        self.assertEqual(stats["deleted"], 2)
        self.assertEqual(stats["bytes"], int(339.773 * 1024**2))

    def test_nothing_transferred(self):
        stats = backup_status.parse_rclone_stats("Transferred:   \t  0 B / 0 B, -, 0 B/s, ETA -\nChecks: 5 / 5, 100%\n")
        self.assertEqual((stats["bytes"], stats["files"], stats["checks"]), (0, 0, 5))


DUMP = """--
-- PostgreSQL database cluster dump
--
CREATE ROLE postgres;
\\connect immich
COPY public.asset_face (id, "assetId", "deletedAt") FROM stdin;
f1\ta1\t\\N
f2\ta2\t\\N
\\.
COPY public.asset (id, "ownerId", type, "originalPath", "deletedAt", "isOffline") FROM stdin;
a1\tu1\tIMAGE\t/p/a\\tb.jpg\t\\N\tf
a2\tu1\tVIDEO\t/p/b.mp4\t2026-11-01 10:00:00+00\tf
a3\tu1\tIMAGE\t/p/c.jpg\t\\N\tf
\\.
COPY public.album (id) FROM stdin;
x
\\.
"""


class TestRestoreTest(unittest.TestCase):
    def test_counts_only_not_deleted_rows_of_the_asset_table(self):
        import gzip
        with tempfile.TemporaryDirectory() as tmp:
            dump = Path(tmp) / "immich_db_20261121_220001.sql.gz"
            with gzip.open(dump, "wt", encoding="utf-8") as fh:
                fh.write(DUMP)
            self.assertEqual(backup_status.count_assets_in_dump(str(dump)), 2)
            plain = Path(tmp) / "no_asset.sql"
            plain.write_text("COPY public.album (id) FROM stdin;\nx\n\\.\n", encoding="utf-8")
            self.assertIsNone(backup_status.count_assets_in_dump(str(plain)))

    def test_result_is_recorded_and_survives_a_backup_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "status.json"
            backup_status.main(["restore-result", "--file", str(path), "--result", "ok", "--message", "Restored",
                                "--started-at", "2026-12-06T11:00:00+05:30", "--completed-at", "2026-12-06T11:07:30+05:30",
                                "--dump-file", "immich_db_20261205_220001.sql.gz", "--expected", "35765", "--restored", "35765"])
            d = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(d["restore_test"]["ok"])
            self.assertEqual(d["restore_test"]["duration_s"], 450)
            backup_status.main(["status", "--file", str(path), "--status", "synced", "--stage", "4",
                                "--started-at", "2026-12-06T22:00:01+05:30", "--completed-at", "2026-12-06T22:05:01+05:30"])
            d = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(d["restore_test"]["restored"], 35765, "a backup run keeps the restore result")
            self.assertEqual(len(d["restore_history"]), 1)


class TestRemoteSwitch(unittest.TestCase):
    def had(self, path, remote):
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            backup_status.main(["had-good-run", "--file", str(path), "--remote", remote])
        return buf.getvalue().strip()

    def test_folders_are_required_only_for_the_remote_that_worked(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "status.json"
            self.assertEqual(self.had(path, "gdrive:"), "0")
            # Written before last_good_remote existed: the old run's remote counts.
            path.write_text(json.dumps({"status": "synced", "remote": "gdrive:", "last_good_at": "2026-11-20T22:06:01"}))
            self.assertEqual(self.had(path, "gdrive:"), "1")
            self.assertEqual(self.had(path, "newdrive:"), "0")
            # A failed run to the new remote keeps the old remote as the last good one.
            backup_status.main(["status", "--file", str(path), "--status", "error", "--stage", "0",
                                "--started-at", "2026-11-22T22:00:01", "--remote", "newdrive:"])
            self.assertEqual(json.loads(path.read_text())["last_good_remote"], "gdrive:")
            self.assertEqual(self.had(path, "newdrive:"), "0")
            backup_status.main(["status", "--file", str(path), "--status", "synced", "--stage", "4",
                                "--started-at", "2026-11-23T22:00:01", "--completed-at", "2026-11-23T23:00:01",
                                "--remote", "newdrive:"])
            self.assertEqual(self.had(path, "newdrive:"), "1")
            self.assertEqual(self.had(path, "gdrive:"), "0")


class TestStatusHistory(unittest.TestCase):
    def run_status(self, path, status, started, completed="", **extra):
        argv = ["status", "--file", str(path), "--status", status, "--stage", extra.pop("stage", "4"),
                "--started-at", started, "--completed-at", completed, "--message", extra.pop("message", "m")]
        for key, value in extra.items():
            argv += ["--" + key.replace("_", "-"), value]
        backup_status.main(argv)
        return json.loads(Path(path).read_text(encoding="utf-8"))

    def test_history_and_last_good(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "status.json"
            # A status.json from before history existed becomes the first history entry.
            path.write_text(json.dumps({"status": "error", "stage": 3, "message": "old failure",
                                        "started_at": "2026-11-21T13:12:12+05:30",
                                        "completed_at": "2026-11-21T13:16:38+05:30", "last_good_at": None}), encoding="utf-8")
            s = self.run_status(path, "syncing", "2026-11-21T22:00:01+05:30", stage="0")
            self.assertEqual(len(s["history"]), 1)
            self.assertEqual(s["history"][0]["outcome"], "error")
            self.assertEqual(s["history"][0]["duration_s"], 266)

            transfer = Path(tmp) / "t.json"
            transfer.write_text(json.dumps({"files": 3, "bytes": 2048}), encoding="utf-8")
            pre = Path(tmp) / "pre.tsv"
            pre.write_text("remote\tok\tanswers\nphoto folder\tok\thas files\n", encoding="utf-8")
            s = self.run_status(path, "synced", "2026-11-21T22:00:01+05:30", "2026-11-21T22:06:01+05:30",
                                transfer_json=str(transfer), preflight_file=str(pre), dump_file="immich_db_x.sql.gz", dump_bytes="99")
            self.assertEqual(s["last_good_at"], "2026-11-21T22:06:01+05:30")
            self.assertTrue(s["preflight"]["ok"])
            self.assertEqual([h["outcome"] for h in s["history"]], ["synced", "error"])
            self.assertEqual(s["history"][0]["files"], 3)
            self.assertEqual(s["history"][0]["duration_s"], 360)
            self.assertEqual(oct(path.stat().st_mode & 0o777), oct(0o644)) if sys.platform != "win32" else None

            s = self.run_status(path, "error", "2026-11-22T22:00:01+05:30", "2026-11-22T22:00:09+05:30",
                                stage="0", message="Pre-flight: remote did not answer")
            self.assertEqual(s["last_good_at"], "2026-11-21T22:06:01+05:30")
            self.assertEqual(len(s["history"]), 3)
            self.assertIsNone(s["transfer"])

    def test_history_is_capped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "status.json"
            for day in range(1, 36):
                started = f"2026-10-{day:02d}T22:00:00" if day <= 31 else f"2026-11-{day - 31:02d}T22:00:00"
                s = self.run_status(path, "synced", started, started)
            self.assertEqual(len(s["history"]), backup_status.HISTORY_LIMIT)


if __name__ == "__main__":
    unittest.main()
