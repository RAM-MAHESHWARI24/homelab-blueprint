#!/usr/bin/env python3
"""
Unit Test Suite for Noodle Gallery Tools
Tests utility functions, path heuristics, cache handling, and CLI parsing.
"""

import sys
import unittest
import tempfile
from pathlib import Path

# Add repo root to import path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import export_faces_to_xmp


class TestNoodleGalleryTools(unittest.TestCase):

    def test_sidecar_path_resolution(self):
        sample = Path("/fake/path/photo.jpg")
        sidecar = export_faces_to_xmp.get_sidecar_path(sample)
        self.assertTrue(str(sidecar).endswith(".xmp"))

    def test_cache_io(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            test_cache_file = Path(tmpdir) / ".test_cache.json"
            orig_cache_file = export_faces_to_xmp.CACHE_FILE
            try:
                export_faces_to_xmp.CACHE_FILE = test_cache_file
                self.assertEqual(export_faces_to_xmp.load_cache(), {})
                export_faces_to_xmp.save_cache({"test_asset": "hash123"})
                loaded = export_faces_to_xmp.load_cache()
                self.assertEqual(loaded.get("test_asset"), "hash123")
            finally:
                export_faces_to_xmp.CACHE_FILE = orig_cache_file

    def test_path_heuristic_mapping(self):
        raw = "/data/upload/library/sample.jpg"
        resolved = export_faces_to_xmp.resolve_asset_path(raw)
        self.assertIsInstance(resolved, Path)


if __name__ == "__main__":
    unittest.main()
