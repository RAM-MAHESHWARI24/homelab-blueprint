#!/usr/bin/env python3
"""
Version consistency: every place that reports the blueprint's version agrees, and
matches the newest released entry in CHANGELOG.md.

v2.1.0 shipped reporting 2.0.0 because nothing tied these together. When cutting a
release, bump all of them in the same pull request (docs/RELEASING.md, step 2):

* setup/installer/deployer.py      BLUEPRINT_VERSION
* setup/server.py                  wizard /api/health "version"
* apps/control-hub/server.py       Control Hub /api/health "version"
* apps/control-hub/docs/openapi.yaml  info.version
* CHANGELOG.md                     newest "## [X.Y.Z] - YYYY-MM-DD" heading

Run: python testing/test_version_consistency.py
"""

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def read(rel):
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def found(rel, pattern):
    match = re.search(pattern, read(rel), flags=re.M)
    return match.group(1) if match else None


def reported_versions():
    return {
        "setup/installer/deployer.py (BLUEPRINT_VERSION)": found("setup/installer/deployer.py", r'^BLUEPRINT_VERSION = "([^"]+)"'),
        "setup/server.py (/api/health)": found("setup/server.py", r'"service": "Homelab Setup Wizard", "version": "([^"]+)"'),
        "apps/control-hub/server.py (/api/health)": found("apps/control-hub/server.py", r'"version": "([^"]+)"'),
        "apps/control-hub/docs/openapi.yaml (info.version)": found("apps/control-hub/docs/openapi.yaml", r"^  version: ([0-9][^\s]*)\s*$"),
    }


def newest_changelog_release():
    return found("CHANGELOG.md", r"^## \[(\d+\.\d+\.\d+)\] - \d{4}-\d{2}-\d{2}")


class TestVersionConsistency(unittest.TestCase):
    def test_every_version_string_is_found(self):
        missing = [where for where, value in reported_versions().items() if not value]
        self.assertEqual(missing, [], "version string not found (pattern changed?)")
        self.assertIsNotNone(newest_changelog_release(), "no dated release heading in CHANGELOG.md")

    def test_versions_agree_with_the_newest_release(self):
        expected = newest_changelog_release()
        wrong = {where: value for where, value in reported_versions().items() if value != expected}
        self.assertEqual(wrong, {}, f"expected {expected} (newest release in CHANGELOG.md)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
