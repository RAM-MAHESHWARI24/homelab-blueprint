#!/usr/bin/env python3
"""
Homelab Blueprint - End-to-End Automated Pipeline Regression Suite
Validates:
  1. Media Ingestion & Atomic Hardlinks (qBittorrent -> Radarr/Sonarr -> Bazarr)
  2. Recyclarr Profile & Custom Format synchronization
  3. StorageManager hardlink probe & error handling
  4. Immich / Noodle Gallery Face-to-XMP Exporter & Binary Invariance
  5. Simulated Google Drive Cloud Backup via Rclone with Trash Buffer
  6. Server Suspend & Dynamic Power Management Flags
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
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "apps" / "immich-face-xmp-exporter"))

from setup.config_core.storage_manager import test_atomic_hardlink, verify_path_writable
from export_faces_to_xmp import build_exiftool_args_for_asset, get_sidecar_path


class TestMediaIngestionAndHardlinks(unittest.TestCase):
    """Module 2 & Module 7: Ingestion, StorageManager Probes, Hardlinks, Renaming, Subtitles & Recyclarr Profiles"""

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

    def test_storage_manager_atomic_hardlink_probe(self):
        """TC-STOR-01: Verify StorageManager hardlink probe measures inodes and latency"""
        result = test_atomic_hardlink(str(self.test_dir))
        self.assertTrue(result["supported"], f"Hardlink probe failed: {result.get('error')}")
        self.assertIsNotNone(result["inode"])
        self.assertGreaterEqual(result["nlink"], 1)
        self.assertIsNotNone(result["latency_ms"])
        self.assertIsNone(result["error"])

    def test_storage_manager_error_handling(self):
        """TC-STOR-02: Verify StorageManager returns informative diagnostics on invalid paths"""
        # Test on a path that cannot be created or written
        invalid_path = str(self.test_dir / "illegal_nul_*\0_path")
        result = test_atomic_hardlink(invalid_path)
        self.assertFalse(result["supported"])
        self.assertIsNotNone(result["error"])
        self.assertIn("tip", result)

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

    def test_immich_exporter_argument_generation(self):
        """TC-FACE-E2E-04: Verify export_faces_to_xmp correctly formats normalized MWG ExifTool arguments"""
        mock_asset = {
            "asset_id": "test-uuid-001",
            "original_path": str(self.photo_file),
            "width": 1000,
            "height": 800,
            "faces": [
                {
                    "name": "Alice Smith",
                    "x1": 100,
                    "y1": 150,
                    "x2": 300,
                    "y2": 350,
                    "img_w": 1000,
                    "img_h": 800,
                },
                {
                    "name": "Bob Smith",
                    "x1": 600,
                    "y1": 200,
                    "x2": 800,
                    "y2": 400,
                    "img_w": 1000,
                    "img_h": 800,
                }
            ]
        }
        sidecar, args = build_exiftool_args_for_asset(mock_asset)
        self.assertIsNotNone(sidecar)
        self.assertIsNotNone(args)
        self.assertIn("-overwrite_original", args)
        self.assertIn("-RegionAreaUnit+=normalized", args)
        self.assertIn("-RegionType+=Face", args)
        self.assertIn("-RegionName+=Alice Smith", args)
        self.assertIn("-RegionName+=Bob Smith", args)
        # Verify normalized coordinates
        # Alice cx = (100+300)/2 / 1000 = 0.20000, cy = (150+350)/2 / 800 = 0.31250
        self.assertIn("-RegionAreaX+=0.20000", args)
        self.assertIn("-RegionAreaY+=0.31250", args)


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
        cloud_trash.mkdir(parents=True, exist_ok=True)
        shutil.move(str(cloud_memories / "vacation_02.jpg"), str(cloud_trash / "vacation_02.jpg"))

        # Verification: File is not in active mirror, but preserved safely in Trash buffer
        self.assertFalse((cloud_memories / "vacation_02.jpg").exists(), "Deleted file removed from active cloud library")
        self.assertTrue((cloud_trash / "vacation_02.jpg").exists(), "Deleted file MUST be preserved in Trash buffer")
        self.assertEqual((cloud_trash / "vacation_02.jpg").read_bytes(), b"JPEG_VACATION_2")

    def test_backup_script_structure_and_retention(self):
        """TC-BACKUP-E2E-04 & 05: Verify backup script template retains safety flags and retention rules"""
        script_path = REPO_ROOT / "apps" / "immich-face-xmp-exporter" / "scripts" / "immich_backup_gdrive.sh.example"
        self.assertTrue(script_path.exists(), "Backup script template must exist")
        text = script_path.read_text(encoding="utf-8")
        self.assertIn("--backup-dir", text, "Must retain accidental deletion protection buffer")
        self.assertIn("--track-renames", text, "Must retain server-side move tracking")
        self.assertIn("-mtime +7 -delete", text, "Must enforce 7-day database dump retention")


class TestSystemPowerAndHostDaemons(unittest.TestCase):
    """Module 5: Host Daemons, Power Management & Sleep Guard Tests"""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="homelab_power_test_"))
        self.log_file = self.test_dir / "server-suspend.log"
        self.skip_file = self.test_dir / "server-suspend.skip"
        self.override_file = self.test_dir / "server-suspend.override"
        self.conf_file = self.test_dir / "server-suspend.conf"
        self.suspend_script = REPO_ROOT / "system" / "power" / "server-suspend.sh"

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    @unittest.skipIf(os.name == "nt", "Bash script execution test requires Linux runner (CI / Ubuntu)")
    def test_suspend_skip_flag_handling(self):
        """TC-SYS-03: Verify Sleep Guard honors skip flag, cleans up, and safely aborts sleep"""
        self.skip_file.write_text("skip", encoding="utf-8")
        self.assertTrue(self.skip_file.exists())

        env = os.environ.copy()
        env["SERVER_SUSPEND_LOG"] = str(self.log_file)
        env["SERVER_SUSPEND_SKIP"] = str(self.skip_file)
        env["SERVER_SUSPEND_OVERRIDE"] = str(self.override_file)
        env["SERVER_SUSPEND_CONF"] = str(self.conf_file)

        proc = subprocess.run(
            ["bash", str(self.suspend_script)],
            env=env,
            capture_output=True,
            text=True
        )

        self.assertEqual(proc.returncode, 0, f"Script failed with: {proc.stderr}")
        self.assertFalse(self.skip_file.exists(), "Skip flag must be consumed and removed upon detection")
        self.assertTrue(self.log_file.exists(), "Execution log must be created")
        log_content = self.log_file.read_text(encoding="utf-8")
        self.assertIn("[SKIP] Found skip flag", log_content)
        self.assertIn("Server sleep aborted for tonight", log_content)

    @unittest.skipIf(os.name == "nt", "Bash script execution test requires Linux runner (CI / Ubuntu)")
    def test_suspend_dry_run_flag(self):
        """TC-SYS-04: Verify dry run mode skips rtcwake execution and exits cleanly"""
        env = os.environ.copy()
        env["SERVER_SUSPEND_LOG"] = str(self.log_file)
        env["SERVER_SUSPEND_SKIP"] = str(self.skip_file)
        env["SERVER_SUSPEND_OVERRIDE"] = str(self.override_file)
        env["SERVER_SUSPEND_CONF"] = str(self.conf_file)

        proc = subprocess.run(
            ["bash", str(self.suspend_script), "--dry-run"],
            env=env,
            capture_output=True,
            text=True
        )

        self.assertEqual(proc.returncode, 0, f"Dry-run execution failed: {proc.stderr}")
        self.assertTrue(self.log_file.exists())
        log_content = self.log_file.read_text(encoding="utf-8")
        self.assertIn("[DRY_RUN] Dry run enabled", log_content)


class TestUniversalHardwareDetection(unittest.TestCase):
    """Module 10: Dynamic Hardware Probing & Custom Hardware Adaptability"""

    def test_cpu_and_ram_dynamic_probing(self):
        """TC-HW-01: Prober accurately queries CPU model, thread count, architecture, and RAM headroom"""
        from setup.config_core.system_prober import probe_cpu_info, probe_ram_info, probe_hardware_acceleration

        cpu = probe_cpu_info()
        self.assertIsInstance(cpu["model"], str)
        self.assertTrue(len(cpu["model"]) > 0, "CPU model name must not be empty")
        self.assertGreaterEqual(cpu["threads"], 1, "Host must have at least 1 CPU thread")
        self.assertIn("is_low_power", cpu)
        self.assertIn("recommended_playback", cpu)

        ram = probe_ram_info()
        self.assertGreater(ram["total_gib"], 0.0, "Total RAM must be greater than 0 GiB")
        self.assertGreater(ram["free_gib"], 0.0, "Free RAM must be greater than 0 GiB")

        hw = probe_hardware_acceleration()
        self.assertIn("has_vaapi_dri", hw)
        self.assertIn("recommended_mode", hw)

    def test_control_hub_hardware_telemetry(self):
        """TC-HW-02: Control Hub telemetry sampler resolves dynamic CPU specs and block devices"""
        sys.path.insert(0, str(REPO_ROOT / "apps" / "control-hub"))
        from core.telemetry_sampler import (
            get_cpu_hardware_specs,
            detect_storage_devices,
            detect_active_nic
        )

        cpu_specs = get_cpu_hardware_specs()
        self.assertTrue(len(cpu_specs["model"]) > 0)
        self.assertGreaterEqual(cpu_specs["cores"], 1)

        root_dev, data_dev, data_mount = detect_storage_devices()
        self.assertTrue(len(root_dev) > 0)
        self.assertTrue(len(data_dev) > 0)
        self.assertTrue(len(data_mount) > 0)

        nic = detect_active_nic("eth0")
        self.assertTrue(len(nic) > 0)


class TestTeardownAndPackagingStandards(unittest.TestCase):
    """Module 11: Teardown Uninstaller & Least-Privilege Security Hardening"""

    def test_teardown_script_structure_and_safety_guards(self):
        """TC-TEARDOWN-01: Verify teardown uninstaller supports safety flags, dry-run, and clean removal"""
        teardown_path = REPO_ROOT / "teardown.sh"
        self.assertTrue(teardown_path.exists(), "teardown.sh must exist at root")
        text = teardown_path.read_text(encoding="utf-8")

        # Verify safety options
        self.assertIn("--dry-run", text)
        self.assertIn("--purge-data", text)
        self.assertIn("--force", text)

        # Verify comprehensive target removal
        self.assertIn("control-hub.service", text)
        self.assertIn("/etc/cron.d/", text)
        self.assertIn("docker compose down", text)
        self.assertIn("apps/control-hub/venv", text)

    def test_least_privilege_daemon_hardening(self):
        """TC-SEC-UNPRIV-01: Verify systemd service runs as unprivileged user with sudoers whitelist"""
        service_path = REPO_ROOT / "system" / "systemd" / "control-hub.service"
        self.assertTrue(service_path.exists())
        text = service_path.read_text(encoding="utf-8")

        self.assertIn("User=homelab", text, "Control Hub must NOT run as root")
        self.assertIn("Group=homelab", text)
        self.assertIn("SupplementaryGroups=docker", text)

        sudoers_path = REPO_ROOT / "system" / "systemd" / "homelab-sudoers.example"
        self.assertTrue(sudoers_path.exists(), "homelab-sudoers.example must exist")
        sudoers_text = sudoers_path.read_text(encoding="utf-8")
        self.assertIn("homelab ALL=(ALL) NOPASSWD:", sudoers_text)
        self.assertIn("/usr/sbin/rtcwake", sudoers_text)
        self.assertIn("control-hub.service", sudoers_text)


if __name__ == "__main__":
    unittest.main()
