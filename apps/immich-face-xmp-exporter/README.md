# Noodle Gallery & Immich Face-to-XMP Exporter & Cloud Backup Toolkit 📸

> Prevent vendor lock-in! Automatically export recognized people, names, and face bounding boxes from **Noodle Gallery** or **Immich** into standard Metadata Working Group (`mwg-rs`) XMP sidecars, with automated database snapshots and cloud mirroring.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![ExifTool](https://img.shields.io/badge/ExifTool-Batch%20Mode-blueviolet.svg)](https://exiftool.org/)
[![Noodle Gallery](https://img.shields.io/badge/Noodle%20Gallery-Compatible-brightgreen.svg)](https://github.com/open-noodle/gallery)
[![Immich](https://img.shields.io/badge/Immich-Compatible-blue.svg)](https://immich.app/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

> This repository is a read-only mirror of a folder in [homelab-blueprint](https://github.com/RAM-MAHESHWARI24/homelab-blueprint), published on every release. Please open issues and pull requests there.

## 🌟 The Problem Solved

By default, **Noodle Gallery** and **Immich** store facial recognitions, person names, and crop bounding boxes strictly inside their internal PostgreSQL database. If you ever migrate away, reinstall, or open your library in professional desktop photo managers (DigiKam, Adobe Lightroom, Adobe Bridge), all your manual and automated tagging effort is lost.

This toolkit provides:
1. **Portable Face Metadata**: Queries the PostgreSQL database for all confirmed, visible face detections and normalizes pixel coordinates to standard MWG region fractions (`RegionAreaX`, `RegionAreaY`, `RegionAreaW`, `RegionAreaH`).
2. **High-Performance Batch ExifTool (`-@`)**: Bundles thousands of sidecar updates into a single persistent ExifTool process, executing **20x–50x faster** than individual CLI calls.
3. **Zero Media Modification**: Original photo and video files are **never modified**; metadata is written strictly to `.xmp` sidecars.
4. **Bi-directional Reverse-Sync**: When Noodle Gallery or Immich rescans sidecars, external tag edits made in DigiKam or Lightroom seamlessly sync back into the web and mobile apps!
5. **Intelligent Path Translation**: Automatically resolves Docker container mount offsets (e.g. `/data/upload/` $\to$ `/data/immich/upload/upload/`) so it runs cleanly on host, cron, or inside containers.
6. **Automated Cloud Backup & Retention**: Provides consistent `pg_dumpall | gzip` snapshots, 7-day retention pruning, and `rclone sync --track-renames` with trash safety buffers.
7. **AI Power Scheduling**: Includes resource-saving scheduler (`immich-ml-control.sh`) to throttle heavy ML inference during human peak hours on low-power mini-PCs / SBCs.

---

## 🚀 Quickstart for Existing Deployments

### 1. Requirements
* Python 3.10+
* ExifTool installed on the host system:
  ```bash
  # Debian / Ubuntu
  sudo apt install -y libimage-exiftool-perl rclone
  ```
* Docker running your Noodle Gallery or Immich stack (needs read access to the database container `immich_postgres`).

### 2. Installation
```bash
git clone https://github.com/RAM-MAHESHWARI24/noodle-gallery-tools.git /opt/noodle-gallery-tools
cd /opt/noodle-gallery-tools
./install.sh      # creates .env and checks for exiftool and docker; no Python packages needed
```
Fill in `IMMICH_URL`, `IMMICH_API_KEY` and the Postgres container name in `.env`.

### 3. Exporting Named Faces
```bash
# Dry-run check without modifying any files
python3 export_faces_to_xmp.py --dry-run

# Test run with first 10 assets
python3 export_faces_to_xmp.py --limit 10

# Full batch export (incremental: skips cached unchanged assets)
python3 export_faces_to_xmp.py

# Force re-export of all assets bypassing cache
python3 export_faces_to_xmp.py --force
```

### 4. Command Line Options & Environment Variables
| Option / Variable | Description |
| :--- | :--- |
| `--dry-run` | Inspect actions without writing `.xmp` sidecars |
| `--limit N` | Export only the first `N` assets (great for testing) |
| `--filter PATH` | Export only assets matching a subpath |
| `--force` | Bypass `.faces_export_cache.json` and rewrite all sidecars |
| `PATH_MAP_FROM` / `PATH_MAP_TO` | Translate container-internal paths to host file paths. Built-in heuristics automatically handle standard Noodle Gallery & Immich volume mounts. |
| `IMMICH_POSTGRES_CONTAINER` | Database container name (default: `immich_postgres`) |
| `DB_NAME` / `DB_USER` | PostgreSQL database and username (default: `immich` / `postgres`) |

---

## ☁️ Automated Nightly Cloud Backup & Media Sync

The included backup script ([`scripts/immich_backup_gdrive.sh.example`](scripts/immich_backup_gdrive.sh.example)):
0. Runs pre-flight checks and stops before touching anything if one fails: the remote answers (`rclone lsd`), its `Memories` and `Immich_Backup/database` folders exist once a run has succeeded (a missing one was probably moved), the photo folder is not empty (an unmounted disk would otherwise be mirrored over the cloud copy), and there is room locally and on the remote.
1. Runs `export_faces_to_xmp.py` to ensure all latest face tags are written to portable XMP sidecars.
2. Dumps a consistent PostgreSQL snapshot (`pg_dumpall | gzip`).
3. Uploads database snapshots to Google Drive / S3 / Backblaze via `rclone copy`, then synchronizes photo binaries and sidecars using `rclone sync --track-renames` with an `Immich_Trash/<date>` buffer to prevent accidental deletions.
4. Applies retention and checks the new dump is on the remote. Locally it keeps the newest `KEEP_LOCAL_DUMPS` (3); on the remote the newest `KEEP_DRIVE_DUMPS` (14) plus the first dump of each of the last `KEEP_DRIVE_MONTHLY` (12) months. Only files named `immich_db_YYYYMMDD_HHMMSS.sql.gz` are ever deleted, so manual dumps stay.

Each step updates `status.json` next to the log (0644, written atomically) with the outcome, pre-flight results, transfer totals, retention and the last 30 runs; [`scripts/backup_status.py`](scripts/backup_status.py) writes it. Only one run happens at a time. A run started by hand (for example from the Control Hub) reads its settings from `/etc/cron.d/immich-backup`, like the nightly job.

### Monthly restore test

A backup is only proven by restoring it. [`scripts/photo_restore_test.sh`](scripts/photo_restore_test.sh)
runs on the first Sunday of every month at 11:00 (`photo-restore-test.timer`; a missed run
happens at the next boot) and:

1. downloads the newest `immich_db_*.sql.gz` **from the remote** (the copy a real restore would use);
2. checks the gzip stream;
3. loads it into a throwaway Postgres container started from the same image as the live
   database (no network, 1 GB memory cap, random password, temporary folder);
4. counts the photos and videos that are not deleted and compares the number with the rows of
   the `asset` table in the dump itself;
5. removes the container and every temporary file, whatever happened.

The result goes into `status.json` (`restore_test`, plus the last 12 in `restore_history`). It
never runs during a backup. Run it by hand with `sudo systemctl start photo-restore-test.service`
or **Run restore test now** in the Control Hub; the log is `restore-test.log` next to the dumps.

To restore for real, see the same steps in reverse: stop the photo server, create an empty
database container from the same image, and feed it the dump with
`gunzip -c immich_db_....sql.gz | docker exec -i <container> psql -U postgres -d postgres`.

### Enabling as a Daily Cron Job:
```bash
sudo ./install.sh --cron
```
This installs `/etc/cron.d/immich-backup` (22:00 nightly), the monthly `photo-restore-test.timer` and `/etc/cron.d/immich-ml`, which starts the ML container at 06:00 and stops it at 10:00. Paths come from `.env`.

---

## 🧪 Integration Testing Suite

A standalone test suite is included in `tests/`:
```bash
python3 tests/test_pipeline.py
```
Validates:
* 4-person photo ingestion into Noodle Gallery via REST API.
* Machine learning facial recognition detection of 4 distinct bounding boxes.
* Interactive/API face tagging.
* Batch ExifTool non-destructive XMP generation with all 4 names and normalized coordinates.
* Database snapshot consistency and simulated cloud sync parity.

---

## 🗺️ Upstream Noodle Gallery PR Integration Roadmap

Our goal is to natively integrate these capabilities directly into [Open-Noodle Gallery](https://github.com/open-noodle/gallery) core. 

### Target Architecture for Native Pull Request:
1. **Background Job Queue**:
   * Add a `FaceExportJob` to Immich's BullMQ job processor, triggered whenever a face is named, merged, or unassigned.
2. **Native ExifTool Service**:
   * Utilize Noodle Gallery's existing ExifTool wrapper to stream `-RegionInfo` metadata commands directly into sidecars without requiring external Python execution.
3. **Admin Settings Toggle**:
   * Surface an option in `Administration -> Settings -> Metadata Settings`:
     * `[x] Enable Face Export to XMP Sidecars (MWG-rs)`
     * `[x] Sync Face Tags to External Storage`

---

## 📄 License
MIT License. Free to use, modify, and protect your family photo archives!
