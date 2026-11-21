# Mediaserver Blueprint 🎬

> Production-tested media ingest & streaming pipeline tailored for low-power hardware, instant atomic hardlinks, ISP DPI SNI bypass, and Recyclarr custom formats.

[![Docker Compose](https://img.shields.io/badge/Docker-Compose%20v2-blue.svg)](https://docs.docker.com/compose/)
[![Atomic Hardlinks](https://img.shields.io/badge/Hardlinks-Instant%200%20I%2FO-success.svg)](#atomic-hardlinks)
[![TMDB Patch](https://img.shields.io/badge/TMDB-DPI%20SNI%20Bypass-orange.svg)](#tmdb-dpi-sni-interceptor)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

> This repository is a read-only mirror of a folder in [homelab-blueprint](https://github.com/RAM-MAHESHWARI24/homelab-blueprint), published on every release. Please open issues and pull requests there.

## 🏗️ Architecture Stack

* **Streaming:** Jellyfin (Direct Play optimized for clients, <1.5% CPU on Haswell i3)
* **Discovery & Requests:** Seerr (Jellyseerr/Overseerr) with TMDB DPI SNI Interceptor
* **Ingest Automation:** Sonarr (TV), Radarr (Movies), Bazarr (Subtitles), Prowlarr (Indexers)
* **Downloader:** qBittorrent
* **Cloudflare Solver:** Byparr (FlareSolverr fork)
* **Quality & Scoring Engine:** Recyclarr (Compact 720p/1080p/4K with +50k Hindi dual-audio score priority)

---

## ⚡ Instant Atomic Hardlinks (0 Disk I/O)

In typical setups, Sonarr/Radarr copy multi-gigabyte media files from torrent folders to media libraries, doubling disk usage and locking mechanical HDDs with heavy I/O.

This blueprint uses a **single ext4 mount**:
```yaml
volumes:
  - /mnt/hdd/data:/data
```
Directory structure inside `/data`:
```
/data/
├── torrents/
│   ├── movies/
│   └── tv/
└── media/
    ├── movies/
    └── tv/
```
Because torrents and media share the exact same root mount, moves and hardlinks take **0.001 seconds**, use **0 extra bytes**, and produce **0 disk I/O**.

---

## 🛡️ TMDB DPI SNI Interceptor (`tmdb-interceptor.js`)

Indian and regional ISPs (Jio, Airtel, ACT) enforce Deep Packet Inspection TLS handshakes resets (`ECONNRESET`) on `api.themoviedb.org`, breaking Seerr movie posters and search.

This blueprint injects `config/seerr/tmdb-interceptor.js` via:
```yaml
environment:
  - NODE_OPTIONS=--dns-result-order=ipv4first --require /app/config/tmdb-interceptor.js
```
It transparently patches Node.js `https.request`, `http.request`, and `globalThis.fetch` to rewrite requests to `api.tmdb.org`, resolving the issue with zero code changes to Seerr itself.

---

## 🚀 Quickstart

### 1. Requirements
* Docker & Docker Compose v2+
* Storage mounted at `/mnt/hdd/data` (or your chosen path)

### 2. Install on its own

```bash
git clone https://github.com/RAM-MAHESHWARI24/homelab-mediaserver.git
cd homelab-mediaserver
./install.sh --data-dir /mnt/hdd/data     # add --byparr for the Byparr proxy
```

`install.sh` creates `.env` with generated passwords, builds the data tree (`torrents/` and `media/` on one filesystem so imports are hardlinks), seeds qBittorrent, starts the stack, waits until every container is healthy, and wires the apps together with [`scripts/wire_arr.py`](scripts/wire_arr.py). It prints the credentials at the end. Re-running it is safe.

It adds no indexers. Pick them in Prowlarr; which indexers you use, and whether they are legal where you live, is up to you.

### 3. Inside homelab-blueprint
The [homelab-blueprint](https://github.com/RAM-MAHESHWARI24/homelab-blueprint) installer does the same from its browser wizard, and its Control Hub adds an indexer picker over Prowlarr's own list.

### 4. Recyclarr Setup
Sync the curated compact profiles with +50k Hindi audio scoring:
```bash
cp recyclarr/mediaserver-profiles.example.yml ~/.config/recyclarr/recyclarr.yml
# Edit with your Radarr and Sonarr API keys:
nano ~/.config/recyclarr/recyclarr.yml
recyclarr sync
```

---

## 💾 Settings Backup (`scripts/media_config_backup.py`)

Rebuilding Sonarr, Radarr, Prowlarr, Bazarr, Seerr and Jellyfin by hand after a disk failure
takes a day. The settings backup saves what cannot be downloaded again:

* every app's configuration and database (series and movie lists, quality profiles, indexers,
  Jellyfin users, libraries and watch history), qBittorrent's settings and torrent list;
* **not** logs, caches, transcodes, cover art (`MediaCover`) or Jellyfin's downloaded metadata
  images, which come back by themselves (set `INCLUDE_JELLYFIN_METADATA=1` to keep those too).

Databases are copied with SQLite's online backup API, so the apps keep running. A typical
install compresses to about 20 MB (`media_config_YYYYMMDD_HHMMSS.tar.zst`).

Each run: pre-flight (folder, rclone, the remote answers, `Media_Backup/` still exists after a
first good run, free space) → snapshot → archive → `rclone copy` to `<remote>Media_Backup/` and a
check that it arrived → retention: 3 archives locally; on the remote the newest 14 plus the first
of each of the last 12 months. Only `media_config_*` archives are ever deleted.

Progress and the last 30 runs are written to `status.json` next to the archives
(default `/var/lib/homelab/media-backups`). The Control Hub's backup card shows them, offers
**Back up now**, and alerts when a run fails or no good run happened for 26 hours.

Inside homelab-blueprint it is installed with the photo backup (same rclone remote) and runs
daily at 21:30 from `/etc/cron.d/media-backup`. On its own:

```bash
sudo GDRIVE_REMOTE=gdrive: MEDIA_APPDATA=/srv/homelab/appdata/mediaserver \
     python3 scripts/media_config_backup.py
```

**Restore:** stop the stack (`docker compose down`), unpack the archive over the settings folder
as root (`tar -I zstd -xpf media_config_....tar.zst -C /srv/homelab/appdata/mediaserver`, which
keeps the owner), start the stack again.

## 🖥️ Live Monitoring & Management
Once launched, the entire media pipeline is monitored in real-time by [Control Hub](https://github.com/RAM-MAHESHWARI24/control-hub):
* **Live Downloads:** qBittorrent ingest speeds, queue progress, and 1-click pause.
* **Port Matrix:** Real-time port connectivity prober for Jellyfin (8096), Seerr (5055), Sonarr (8989), Radarr (7878), Prowlarr (9696), and Bazarr (6767).
* **Container Logs:** recent logs for each container, read inline from the Service Matrix.

---

## 📄 License
MIT License. Part of [homelab-blueprint](https://github.com/RAM-MAHESHWARI24/homelab-blueprint).
