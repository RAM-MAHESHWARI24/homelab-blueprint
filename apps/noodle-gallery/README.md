# Noodle Gallery (Open-Noodle) 🍜📸

> High-performance, low-power self-hosted photo & video cloud featuring VectorChord similarity search, AI facial recognition, automatic camera backups, and seamless mobile app compatibility.

[![Docker Compose](https://img.shields.io/badge/Docker-Compose%20v2-blue.svg)](https://docs.docker.com/compose/)
[![Open-Noodle](https://img.shields.io/badge/Open--Noodle-Gallery-orange.svg)](https://github.com/open-noodle)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## 🌟 What is Noodle Gallery?

**Noodle Gallery** is a fast, community-optimized distribution of the open-source photo gallery suite. It retains full protocol and API compatibility with Immich mobile apps while offering performance enhancements tailored for low-power homelab servers:
* **📱 Full Mobile App Compatibility:** Connects seamlessly with Immich mobile apps for Android and iOS for background auto-backup.
* **🧠 Vector AI Search & Face Recognition:** Powered by VectorChord embeddings and CLIP neural search for lightning-fast visual discovery.
* **⚡ Low-Power CPU Scheduling:** Pre-configured with our off-peak machine learning scheduler (`system/power/immich-ml-control.sh`) so your CPU stays at <1.5% load during waking hours.
* **🔒 Zero Vendor Lock-In:** Complements our [`apps/immich-face-xmp-exporter/`](../immich-face-xmp-exporter/) to write all facial recognition metadata directly into universal XMP sidecars.

---

## 🚀 Quickstart

### 1. Requirements
* Docker & Docker Compose v2+
* Linux host (Ubuntu 24.04/26.04 recommended)
* Storage allocation:
  * **SSD Directory:** For PostgreSQL vector embeddings (`./data/postgres`)
  * **HDD Directory:** For photo uploads and media library (`/mnt/hdd/immich`)

### 2. Configure Environment
```bash
cd apps/noodle-gallery
cp .env.example .env
nano .env
```
Key variables to verify:
* `UPLOAD_LOCATION`: Path to your photo storage mount (e.g. `/mnt/hdd/immich`)
* `DB_DATA_LOCATION`: Fast SSD path for PostgreSQL (`./data/postgres`)
* `DB_PASSWORD`: Strong alphanumeric database password

### 3. Launch the Stack
```bash
docker compose up -d
```
The web gallery will be live at:
```
http://<YOUR_SERVER_IP>:2283
```

---

## 📱 Mobile App Setup (Android & iOS)

1. Install the **Immich** app from Google Play or Apple App Store.
2. In the login screen:
   * **Server Endpoint:** `http://<YOUR_SERVER_IP>:2283` (or your Tailscale IP `http://100.x.y.z:2283`)
   * Log in with your admin credentials.
3. Enable **Auto Backup** to sync your mobile camera roll.

---

## ⚡ Off-Peak Machine Learning Scheduling

To prevent continuous CPU burn on low-power processors (such as 2-core Haswell i3 chips):
1. `gallery-machine-learning` is set to `restart: "no"`.
2. A nightly cron job (`system/cron.d/immich-ml`) runs `system/power/immich-ml-control.sh` during the night (e.g. 02:00 - 05:00 AM) to batch-process any newly uploaded photos, then gracefully stops the ML container.
3. This keeps daytime idle CPU usage below 2% and thermals cool.

---

## 🛡️ Automated Backups & Cloud Mirror

PostgreSQL database snapshots are dumped nightly via:
* **Backup Script:** [`apps/immich-face-xmp-exporter/scripts/immich_backup_gdrive.sh.example`](../immich-face-xmp-exporter/scripts/immich_backup_gdrive.sh.example)
* **Cron Job:** [`system/cron.d/immich-backup`](../../system/cron.d/immich-backup)
* **Status Dashboard:** Real-time sync gauges on [Control Hub](../control-hub/).

---

## 📄 License
MIT License. Part of the [Homelab Blueprint](../../README.md) monorepo.
