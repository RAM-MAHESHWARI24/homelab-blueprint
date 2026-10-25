# Storage Architecture & Atomic Hardlinks Blueprint 💾

## 1. Overview
In a low-power home server with mechanical hard drives (5400 RPM), disk I/O is the primary bottleneck. Traditional setups copy multi-gigabyte media files from torrent completion folders to media libraries, causing:
1. Double disk space usage.
2. 100% disk I/O saturation, leading to video streaming stutters.
3. Premature drive wear.

## 2. The Solution: Single-Mount Atomic Hardlinking
An **atomic hardlink** creates a second filesystem pointer to the exact same physical inodes on disk:
- Time to complete: **0.001 seconds** (instant).
- Disk space used: **0 bytes**.
- Disk I/O generated: **0 KB/s**.

### Crucial Requirement
Hardlinks **cannot cross filesystem boundaries or Docker volume mounts**. Every container in the pipeline (qBittorrent, Sonarr, Radarr) must mount the **exact same root directory** using the exact same internal mount path.

## 3. Directory Layout Blueprint
Mount host directory `/mnt/hdd/data` as `/data` in all containers:

```
/mnt/hdd/data/
├── torrents/
│   ├── movies/
│   └── tv/
└── media/
    ├── movies/
    └── tv/
```

### Docker Volume Mapping Example
```yaml
services:
  qbittorrent:
    volumes:
      - /mnt/hdd/data:/data
  sonarr:
    volumes:
      - /mnt/hdd/data:/data
  radarr:
    volumes:
      - /mnt/hdd/data:/data
```

## 4. In-App Configuration
* **qBittorrent:** Default Save Path: `/data/torrents`
* **Sonarr:** Root Folder: `/data/media/tv`, Category: `tv`
* **Radarr:** Root Folder: `/data/media/movies`, Category: `movies`
* In Sonarr/Radarr: Ensure **"Use Hardlinks instead of Copy"** is enabled under Media Management.
