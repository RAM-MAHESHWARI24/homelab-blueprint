"""Unit tests for tv_updater double-logging suppression (Phase 1D)."""

from __future__ import annotations

import os
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


class TestTvUpdaterLogging(unittest.TestCase):
    def test_stdout_suppression_when_env_disabled_or_same_inode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "tv_updater.log"
            log_path.write_text("", encoding="utf-8")

            with mock.patch.dict(os.environ, {"TV_AUTOUPDATER_LOG_STDOUT": "0"}):
                self.assertTrue(tv_updater._stdout_is_log_file(log_path))

            fake_stat = SimpleNamespace(st_dev=42, st_ino=9001)
            with mock.patch.dict(os.environ, {"TV_AUTOUPDATER_LOG_STDOUT": "1"}), \
                 mock.patch.object(os, "fstat", return_value=fake_stat), \
                 mock.patch.object(Path, "stat", return_value=fake_stat):
                self.assertTrue(tv_updater._stdout_is_log_file(log_path))

            other_stat = SimpleNamespace(st_dev=42, st_ino=9002)
            with mock.patch.dict(os.environ, {"TV_AUTOUPDATER_LOG_STDOUT": "1"}), \
                 mock.patch.object(os, "fstat", return_value=other_stat), \
                 mock.patch.object(Path, "stat", return_value=fake_stat):
                self.assertFalse(tv_updater._stdout_is_log_file(log_path))


if __name__ == "__main__":
    unittest.main()
