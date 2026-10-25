# Mediaserver Blueprint 🎬

> Production-tested media ingest & streaming pipeline tailored for low-power hardware, instant atomic hardlinks, ISP DPI SNI bypass, and Recyclarr custom formats.

[![Docker Compose](https://img.shields.io/badge/Docker-Compose%20v2-blue.svg)](https://docs.docker.com/compose/)
[![Atomic Hardlinks](https://img.shields.io/badge/Hardlinks-Instant%200%20I%2FO-success.svg)](#atomic-hardlinks)
[![TMDB Patch](https://img.shields.io/badge/TMDB-DPI%20SNI%20Bypass-orange.svg)](#tmdb-dpi-sni-interceptor)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

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

### 2. Configuration & Automated Provisioning
You can configure and deploy the media server stack in two ways:
* **Automated Web GUI (Recommended):** Use the [Homelab Setup Wizard](../../setup/README.md) (`http://<server-ip>:8000`) or [Control Hub Settings](../../apps/control-hub/README.md) (`http://<server-ip>:7575`). It automatically tests your disk mounts with live `os.link` hardlink inode probes and auto-generates API keys.
* **Manual Setup:**
```bash
cp .env.example .env
nano .env
```

### 3. Launch Stack
```bash
docker compose up -d
```

### 4. Recyclarr Setup
Sync the curated compact profiles with +50k Hindi audio scoring:
```bash
cp recyclarr/mediaserver-profiles.example.yml ~/.config/recyclarr/recyclarr.yml
# Edit with your Radarr and Sonarr API keys:
nano ~/.config/recyclarr/recyclarr.yml
recyclarr sync
```

---

## 🖥️ Live Monitoring & Management
Once launched, the entire media pipeline is monitored in real-time by [Control Hub](../control-hub/):
* **Live Downloads:** qBittorrent ingest speeds, queue progress, and 1-click pause.
* **Port Matrix:** Real-time port connectivity prober for Jellyfin (8096), Seerr (5055), Sonarr (8989), Radarr (7878), Prowlarr (9696), and Bazarr (6767).
* **Container Logs:** 1-Click Dozzle log streaming with 12-char hex Docker ID deep linking.

---

## 📄 License
MIT License. Part of the [Homelab Blueprint](../../README.md) monorepo.
