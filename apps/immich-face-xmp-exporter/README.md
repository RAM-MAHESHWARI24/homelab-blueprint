# Immich Face-to-XMP Exporter & Cloud Backup Toolkit 📸

> Prevent vendor lock-in! Automatically export Immich recognized people, names, and face bounding boxes into standard Metadata Working Group (`mwg-rs`) XMP sidecars.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![ExifTool](https://img.shields.io/badge/ExifTool-Batch%20Mode-blueviolet.svg)](https://exiftool.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## 🌟 The Problem Solved

By default, **Immich** stores face recognitions, person names, and crop bounding boxes inside its internal PostgreSQL database. If you ever migrate away from Immich, reinstall, or open your library in professional desktop photo managers (DigiKam, Adobe Lightroom, Adobe Bridge), all your tagging effort is lost.

This toolkit:
1. Queries the Immich PostgreSQL database for all confirmed, visible face detections.
2. Normalizes pixel coordinates to standard MWG region fractions (`RegionAreaX`, `RegionAreaY`, `RegionAreaW`, `RegionAreaH`).
3. Writes or updates `.xmp` sidecar files directly beside original media using **Batch ExifTool (`-@`)** (running 20x–50x faster than single CLI calls).
4. **Zero Media Modification:** Original photo and video files are **never modified**.
5. **Reverse-Sync Compatible:** When Immich scans sidecar files, external edits made in DigiKam or Lightroom seamlessly sync back into Immich!

---

## 🚀 Quickstart

### 1. Requirements
* Python 3.10+
* ExifTool installed on the host system:
  ```bash
  # Debian / Ubuntu
  sudo apt install libimage-exiftool-perl
  ```
* Docker (with access to `immich_postgres` container)

### 2. Exporting Named Faces
```bash
# Clone the repository
git clone https://github.com/your-username/immich-face-xmp-exporter.git /opt/immich-face-xmp-exporter
cd /opt/immich-face-xmp-exporter

# Test run with first 10 assets
python3 export_faces_to_xmp.py --limit 10

# Dry-run check without modifying files
python3 export_faces_to_xmp.py --dry-run

# Full batch export (incremental: skips cached unchanged assets)
python3 export_faces_to_xmp.py
```

### 3. Command Line Options
| Flag | Description |
| :--- | :--- |
| `--dry-run` | Inspect actions without writing `.xmp` sidecars |
| `--limit N` | Export only the first `N` assets (great for testing) |
| `--filter PATH` | Export only assets matching a subpath |
| `--force` | Bypass `.faces_export_cache.json` and rewrite all sidecars |

---

## ☁️ Nightly Cloud Backup & Media Sync

See [`scripts/immich_backup_gdrive.sh.example`](scripts/immich_backup_gdrive.sh.example) for an automated backup script that:
* Dumps PostgreSQL database consistent snapshots (`pg_dumpall | gzip`).
* Prunes dumps older than 7 days.
* Syncs with cloud storage (Google Drive, Backblaze B2, S3) using `rclone sync --track-renames`.
* Moves deleted/renamed items to an `Immich_Trash/<date>` buffer to prevent accidental data loss.

---

## 📄 License
MIT License. Free to use and protect your family photo archives!
