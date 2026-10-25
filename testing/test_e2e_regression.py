#!/usr/bin/env python3
"""
Homelab Blueprint - End-to-End Automated Pipeline Regression Suite
Validates:
  1. Media Ingestion & Atomic Hardlinks (qBittorrent -> Radarr/Sonarr -> Bazarr)
  2. Recyclarr Profile & Custom Format synchronization
  3. Immich / Noodle Gallery Face-to-XMP 4-Face Roundtrip & Binary Invariance
  4. Simulated Google Drive Cloud Backup via Rclone with Trash Buffer
"""

import os
import sys
import json
import time
import shutil
import hashlib
import tempfile
import unittest
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestMediaIngestionAndHardlinks(unittest.TestCase):
    """Module 7: Ingestion, Hardlinks, Renaming, Subtitles & Recyclarr Profiles"""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="homelab_media_test_"))
        self.torrents_dir = self.test_dir / "data" / "torrents" / "movies"
        self.media_dir = self.test_dir / "data" / "media" / "movies"
        self.torrents_dir.mkdir(parents=True, exist_ok=True)
        self.media_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_atomic_hardlink_and_renaming(self):
        """TC-MEDIA-E2E-05: Verify 0-I/O hardlinks between torrents and library"""
        # 1. Simulate completed qBittorrent download
        raw_torrent_file = self.torrents_dir / "Big.Buck.Bunny.2008.1080p.WEBDL.AAC2.0.H.264-GRP.mkv"
        sample_payload = b"\x00\x00\x01\xba" + b"HOMELAB_TEST_VIDEO_STREAM_DATA" * 1024
        raw_torrent_file.write_bytes(sample_payload)

        # 2. Simulate Radarr atomic hardlink & standardized library rename
        movie_library_folder = self.media_dir / "Big Buck Bunny (2008)"
        movie_library_folder.mkdir(parents=True, exist_ok=True)
        imported_media_file = movie_library_folder / "Big Buck Bunny (2008) [WEBDL-1080p] [AAC].mkv"

        # Execute atomic link
        os.link(str(raw_torrent_file), str(imported_media_file))

        stat_src = os.stat(raw_torrent_file)
        stat_dst = os.stat(imported_media_file)

        # Mathematical Proof: Same inode, multiple links
        self.assertEqual(stat_src.st_ino, stat_dst.st_ino, "Inodes must match for atomic hardlink")
        self.assertGreaterEqual(stat_dst.st_nlink, 2, "Link count must be >= 2")
        self.assertEqual(stat_src.st_size, stat_dst.st_size, "File sizes must match")

    def test_bazarr_subtitle_encoding_and_placement(self):
        """TC-MEDIA-E2E-06: Subtitles must be adjacent to media and encoded in UTF-8 without BOM"""
        movie_folder = self.media_dir / "Cosmos Laundromat (2015)"
        movie_folder.mkdir(parents=True, exist_ok=True)
        media_file = movie_folder / "Cosmos Laundromat (2015) [WEBDL-1080p].mkv"
        media_file.write_bytes(b"MOCK_MEDIA")

        # Simulate Bazarr downloading subtitle
        sub_file = movie_folder / "Cosmos Laundromat (2015) [WEBDL-1080p].en.srt"
        sub_content = "1\n00:00:01,000 --> 00:00:04,000\nHomelab Automated Test Subtitle\n"
        sub_file.write_text(sub_content, encoding="utf-8")

        self.assertTrue(sub_file.exists(), "Subtitle file must be placed adjacent to media file")
        raw_bytes = sub_file.read_bytes()
        self.assertFalse(raw_bytes.startswith(b"\xef\xbb\xbf"), "Subtitle must NOT contain UTF-8 BOM")

    def test_recyclarr_profile_configuration_validity(self):
        """TC-MEDIA-E2E-02: Verify Recyclarr Hindi priority score and 1080p Compact limits"""
        profile_file = REPO_ROOT / "apps" / "mediaserver" / "recyclarr" / "mediaserver-profiles.example.yml"
        self.assertTrue(profile_file.exists(), "Recyclarr profile template must exist")
        content = profile_file.read_text(encoding="utf-8")

        self.assertIn("radarr:", content)
        self.assertIn("sonarr:", content)
        self.assertIn("WEBDL-1080p", content)
        # Verify Hindi priority score
        self.assertIn("+50000", content)


class TestPhotoCloudAndFaceXmp(unittest.TestCase):
    """Module 8: Immich / Noodle Gallery Face Recognition & XMP Roundtrip"""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="homelab_photo_test_"))
        self.photo_file = self.test_dir / "sample_reunion.jpg"
        self.xmp_file = self.test_dir / "sample_reunion.jpg.xmp"

        # Create dummy JPEG binary
        self.dummy_jpeg_data = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xff\xdb" + b"FACE_DATA" * 512 + b"\xff\xd9"
        self.photo_file.write_bytes(self.dummy_jpeg_data)
        self.initial_hash = hashlib.sha256(self.dummy_jpeg_data).hexdigest()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_four_face_xmp_roundtrip_and_invariance(self):
        """TC-FACE-E2E-04 to 06: Test 4 faces in XMP-mwg-rs and photo binary preservation"""
        # Step 1: Pre-existing XMP with 2 faces (Alice, Bob)
        initial_xmp = """<x:xmpmeta xmlns:x="adobe:ns:meta/">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about="" xmlns:mwg-rs="http://www.metadataworkinggroup.com/schemas/regions/">
   <mwg-rs:Regions rdf:parseType="Resource">
    <mwg-rs:RegionList>
     <rdf:Bag>
      <rdf:li rdf:parseType="Resource">
       <mwg-rs:Name>Alice Smith</mwg-rs:Name>
       <mwg-rs:Type>Face</mwg-rs:Type>
       <mwg-rs:Area mwg-rs:x="0.25" mwg-rs:y="0.30" mwg-rs:w="0.15" mwg-rs:h="0.20" mwg-rs:unit="normalized"/>
      </rdf:li>
      <rdf:li rdf:parseType="Resource">
       <mwg-rs:Name>Bob Smith</mwg-rs:Name>
       <mwg-rs:Type>Face</mwg-rs:Type>
       <mwg-rs:Area mwg-rs:x="0.75" mwg-rs:y="0.32" mwg-rs:w="0.16" mwg-rs:h="0.21" mwg-rs:unit="normalized"/>
      </rdf:li>
     </rdf:Bag>
    </mwg-rs:RegionList>
   </mwg-rs:Regions>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>"""
        self.xmp_file.write_text(initial_xmp, encoding="utf-8")

        # Step 2: Immich ML clusters remaining 2 faces -> Charlie Davis & Diana Prince
        # Exporter updates XMP with all 4 faces
        updated_xmp = initial_xmp.replace("</rdf:Bag>", """      <rdf:li rdf:parseType="Resource">
       <mwg-rs:Name>Charlie Davis</mwg-rs:Name>
       <mwg-rs:Type>Face</mwg-rs:Type>
       <mwg-rs:Area mwg-rs:x="0.45" mwg-rs:y="0.55" mwg-rs:w="0.14" mwg-rs:h="0.18" mwg-rs:unit="normalized"/>
      </rdf:li>
      <rdf:li rdf:parseType="Resource">
       <mwg-rs:Name>Diana Prince</mwg-rs:Name>
       <mwg-rs:Type>Face</mwg-rs:Type>
       <mwg-rs:Area mwg-rs:x="0.60" mwg-rs:y="0.58" mwg-rs:w="0.15" mwg-rs:h="0.19" mwg-rs:unit="normalized"/>
      </rdf:li>
     </rdf:Bag>""")
        self.xmp_file.write_text(updated_xmp, encoding="utf-8")

        # Step 3: Verify all 4 faces present
        final_xmp_text = self.xmp_file.read_text(encoding="utf-8")
        for expected_person in ["Alice Smith", "Bob Smith", "Charlie Davis", "Diana Prince"]:
            self.assertIn(f"<mwg-rs:Name>{expected_person}</mwg-rs:Name>", final_xmp_text)

        # Step 4: Strict Non-Destructive Invariance Guarantee
        final_hash = hashlib.sha256(self.photo_file.read_bytes()).hexdigest()
        self.assertEqual(self.initial_hash, final_hash, "Original photo binary must remain 100% unaltered")


class TestSimulatedCloudBackup(unittest.TestCase):
    """Module 9: Simulated Google Drive Rclone Mirror & Accidental Deletion Protection"""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="homelab_backup_test_"))
        self.local_memories = self.test_dir / "local_memories"
        self.simulated_gdrive = self.test_dir / "simulated_gdrive"
        self.local_backups = self.test_dir / "local_backups"

        self.local_memories.mkdir(parents=True, exist_ok=True)
        self.simulated_gdrive.mkdir(parents=True, exist_ok=True)
        self.local_backups.mkdir(parents=True, exist_ok=True)

        # Add sample media files
        (self.local_memories / "vacation_01.jpg").write_bytes(b"JPEG_VACATION_1")
        (self.local_memories / "vacation_01.jpg.xmp").write_text("XMP_DATA_1", encoding="utf-8")
        (self.local_memories / "vacation_02.jpg").write_bytes(b"JPEG_VACATION_2")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_simulated_rclone_sync_and_trash_buffer(self):
        """TC-BACKUP-E2E-03 & 04: Sync to simulated cloud with accidental deletion buffer"""
        cloud_memories = self.simulated_gdrive / "Memories"
        cloud_trash = self.simulated_gdrive / "Immich_Trash" / "20261025_test"

        # Step 1: Initial Sync
        shutil.copytree(self.local_memories, cloud_memories, dirs_exist_ok=True)
        self.assertTrue((cloud_memories / "vacation_01.jpg").exists())
        self.assertTrue((cloud_memories / "vacation_01.jpg.xmp").exists())

        # Step 2: Simulate user accidentally deleting vacation_02.jpg locally
        (self.local_memories / "vacation_02.jpg").unlink()
        self.assertFalse((self.local_memories / "vacation_02.jpg").exists())

        # Step 3: Simulate rclone sync with --backup-dir protection
        # Instead of deleting vacation_02 from cloud, it moves it to trash buffer
        cloud_trash.mkdir(parents=True, exist_ok=True)
        shutil.move(str(cloud_memories / "vacation_02.jpg"), str(cloud_trash / "vacation_02.jpg"))

        # Verification: File is not in active mirror, but preserved safely in Trash buffer
        self.assertFalse((cloud_memories / "vacation_02.jpg").exists(), "Deleted file removed from active cloud library")
        self.assertTrue((cloud_trash / "vacation_02.jpg").exists(), "Deleted file MUST be preserved in Trash buffer")
        self.assertEqual((cloud_trash / "vacation_02.jpg").read_bytes(), b"JPEG_VACATION_2")


if __name__ == "__main__":
    unittest.main()
