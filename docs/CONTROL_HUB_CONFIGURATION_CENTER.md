# Control Hub: Node Configuration & AI Copilot Integration

The modular configuration engine originally built for the onboarding Setup Wizard has been seamlessly integrated directly into the custom dashboard (**Control Hub** at port `7575`).

Administrators can now inspect, live-test, and update their entire homelab topology in real time without manually editing `.env` files or risking SSH lockouts.

---

## 1. Architecture Overview

```
                                +-----------------------------+
                                | Control Hub Web Dashboard   |
                                |     (http://<host>:7575)    |
                                +--------------+--------------+
                                               |
                     +-------------------------+-------------------------+
                     |                                                   |
        [⚙️ Node Settings Modal]                              [🤖 AI Copilot Modal]
                     |                                                   |
  +------------------+------------------+             +------------------+------------------+
  | - 📁 Storage & Atomic Hardlinks     |             | - CPU & Haswell Architecture Profile|
  | - 🔌 13-Service Port Matrix Prober  |             | - Memory Headroom (Total vs Free)   |
  | - 🔐 PUID/PGID & Crypto Secrets Gen |             | - GPU /dev/dri/renderD128 (VAAPI)   |
  | - 🌐 Safe Netplan Static IP (45s)   |             | - 1-Click Compact Prompt (~300 tok) |
  | - 🚀 Fast Launch Setup Wizard (8000)|             | - Links to Repository Runbooks      |
  +------------------+------------------+             +-------------------------------------+
                     |
                     v
   +------------------------------------+
   | Flask Blueprint (config_center.py) |
   +-----------------+------------------+
                     |
       +-------------+-------------+
       |                           |
       v                           v
+----------------+      +---------------------+
| setup/         |      | Master Root .env &  |
| config_core    |      | Blueprint App .envs |
+----------------+      +---------------------+
```

---

## 2. Key Integrated Features

### 📁 1. Single-Mount Storage & Atomic Hardlink Tester
- **Path Config:** Live modification of `HDD_DATA` (`/mnt/hdd/data`) and `HDD_MEMORIES` (`/mnt/hdd/Memories`).
- **Live Hardlink Verification:** Runs real `os.link()` checks directly on host filesystem mounts to verify single-mount ext4/xfs compliance (returns Inode number, link count, and latency in ms).
- **Rule Enforcement:** Warns against cross-device (`EXDEV`) link issues where downloads and media are on separate mounts, preventing slow duplicate file copying.

### 🔌 2. Real-Time 13-Service Port Conflict Prober
- Probes IPv4 socket bindings for all 13 services:
  - `7575` Control Hub Dashboard
  - `8096` Jellyfin HTTP
  - `8920` Jellyfin HTTPS
  - `5055` Seerr (Media Discovery)
  - `8080` qBittorrent Web UI
  - `6881` qBittorrent Peer Listening
  - `8989` Sonarr TV Automation
  - `7878` Radarr Movie Automation
  - `9696` Prowlarr Indexer Proxy
  - `6767` Bazarr Subtitle Manager
  - `8191` Byparr Cloudflare Solver
  - `2283` Noodle Gallery / Immich Web
  - `8000` Homelab Setup Wizard
- Displays live status pills (`Active / Bound` or `Available`) and direct **"Open Web UI ↗"** buttons for active services.

### 🔐 3. User Permissions & High-Entropy Credentials
- **Auto-Detect User:** 1-click detection of host Linux `PUID` and `PGID` to ensure container volumes match host permissions.
- **Crypto Secrets Generator:** 1-click generation of strong alphanumeric passwords (safe for PostgreSQL and shell interpolation) and 32-character API keys for Radarr, Sonarr, and Prowlarr.

### 🌐 4. Safe Netplan Static IP with 45s Auto-Rollback
- Auto-detects active network interfaces, gateway, and DNS servers.
- Generates standard Netplan v2 YAML configuration.
- **Safety Guarantee:** Applies with `netplan try --timeout 45`. If connection drops or network configuration fails, Netplan automatically rolls back to the backup network configuration within 45 seconds, protecting remote SSH sessions from getting severed.

### 🤖 5. AI Copilot Diagnostics & Compact Prompt Exporter
- Probes CPU model, architecture, thread count, and low-power / Direct Play profile.
- Probes RAM headroom and `/dev/dri/renderD128` hardware acceleration status.
- Generates a **token-optimized diagnostic prompt (~300 tokens)** tailored for ChatGPT, Claude, and Antigravity:
  - Includes real-time hardware specs, mount paths, network settings, and key blueprint architectural rules.
  - Features 1-click **"📋 Copy AI Prompt"** with visual clipboard confirmation.

### 📊 6. Universal Hardware Telemetry Display
- **Dynamic Vitals Card:** Automatically populates host CPU model, core/thread count, physical memory headroom, and root/storage partition sizes dynamically without hardcoded machine assumptions.
- **Dynamic Block Device Throughput:** Dynamically identifies active root and storage block devices (`nvme*`, `sd*`, `vd*`, `mmcblk*`) and renders read/write I/O telemetry in real time.

---

## 3. Visual Verification

| Feature | Screenshot |
| :--- | :--- |
| **Top Cyber-HUD Header** | ![Header](assets/control-hub/hub_header_settings_ai.png) |
| **Storage & Hardlink Tester** | ![Hardlinks](assets/control-hub/hub_settings_hardlink_test.png) |
| **13-Service Port Matrix** | ![Ports](assets/control-hub/hub_settings_port_matrix.png) |
| **AI Copilot Diagnostics** | ![AI Copilot](assets/control-hub/hub_ai_copilot_diagnostics.png) |
