# Homelab Blueprint & All-in-One Monorepo 🏠⚡

> A production-tested, low-power homelab monorepo featuring atomic media hardlinks, automated RTC wake power management, ISP SNI DPI bypasses, silent Android TV maintenance, and non-vendor-locked photo metadata tools.

[![Ubuntu](https://img.shields.io/badge/Ubuntu-26.04%20LTS-orange.svg)](https://ubuntu.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Monorepo](https://img.shields.io/badge/Monorepo-All--in--One-success.svg)](#repository-layout)

---

## 🌟 Why an All-in-One Monorepo?

Instead of juggling multiple scattered repositories and tricky Git submodule commands, this repository contains **everything in one place**. A single `git clone` gives you the full server orchestration suite, hardware optimization runbooks, custom dashboard, TV updater, and media ingestion stack:

```
homelab-blueprint/
├── README.md                           # Master homelab overview & quickstart
├── ARCHITECTURE.md                     # Deep technical dive (storage, CPU, memory, power)
├── .env.example                        # Unified server configuration template
├── docs/                               # Engineering runbooks & deep dives
│   ├── STORAGE_AND_HARDLINKS.md        # Single ext4 mount atomic hardlink guide (0 disk I/O)
│   ├── POWER_MANAGEMENT_RTCWAKE.md     # S3 suspend (1.2W) & post-wake self-healing runbook
│   ├── NETWORKING_TAILSCALE_SAMBA.md   # Tailscale subnet routing & Samba dual shares
│   ├── HASWELL_DIRECT_PLAY_GUIDE.md    # Low-power CPU transcode protection & direct play
│   └── GIGABIT_LAN_DIAGNOSTICS.md      # Ethernet link auto-negotiation & PHY diagnostics
├── system/                             # Host OS automation & configurations
│   ├── cron.d/                         # Template cron definitions (suspend, backup, updates)
│   ├── systemd/                        # Systemd unit files (Control Hub daemon)
│   ├── power/                          # Suspend, RTC wake, and ML container scripts
│   ├── networking/                     # Tailscale forwarding & Samba shares (smb.conf)
│   └── maintenance/                    # Automated Watchtower updater with log rotation
└── apps/                               # Real application source trees & pipelines
    ├── control-hub/                    # Custom Python/Flask dark glassmorphism dashboard (<25MB RAM)
    ├── tv-updater/                     # Zero-overhead background Android TV ADB updater
    ├── noodle-gallery/                 # High-performance photo & video cloud with VectorChord search
    ├── immich-face-xmp-exporter/       # Non-destructive face-to-XMP sidecar exporter & cloud sync
    └── mediaserver/                    # Complete Docker Compose media stack with TMDB DPI patch
```

---

## 📦 What's Inside

| Module | Location | Purpose | Key Tech |
| :--- | :--- | :--- | :--- |
| **Control Hub** | [`apps/control-hub/`](apps/control-hub/) | High-performance dashboard & server management daemon | Python, Flask, Vanilla ES6 |
| **CleanYourTV** | [`apps/tv-updater/`](apps/tv-updater/) | Silent background Android TV ADB app updater | Python, Network ADB (Port 5555) |
| **Noodle Gallery** | [`apps/noodle-gallery/`](apps/noodle-gallery/) | High-performance photo cloud with vector search | Open-Noodle Gallery, PostgreSQL, Valkey |
| **Immich XMP Tools** | [`apps/immich-face-xmp-exporter/`](apps/immich-face-xmp-exporter/) | Batch ExifTool face-to-XMP sidecar generator & cloud backup | Python, ExifTool, Rclone |
| **Media Pipeline** | [`apps/mediaserver/`](apps/mediaserver/) | Jellyfin, Arr stack, atomic hardlinks & TMDB ISP patch | Docker Compose, Jellyfin, Arr suite |

---

## 🚀 Quickstart & Automated Web GUI Setup

Deploy your homelab on a fresh Ubuntu Server in under 60 seconds with our zero-dependency Web GUI onboarding wizard.

### Option A: 1-Line Automated Bootstrap (Fastest)
Run this single command on your Ubuntu Server terminal:
```bash
curl -sSL https://raw.githubusercontent.com/RAM-MAHESHWARI24/homelab-blueprint/main/bootstrap.sh | sudo bash
```

### Option B: Standard Git Clone
```bash
git clone https://github.com/RAM-MAHESHWARI24/homelab-blueprint.git /opt/homelab-blueprint
cd /opt/homelab-blueprint
sudo ./setup.sh
```

### 🌐 Open the Web GUI in your Browser
The terminal will display your clickable LAN URL:
```
👉 http://<your-server-ip>:8000   (from your laptop, phone, or console)
```

Select your configuration experience:
* **⚡ Express Mode ("Least Setup"):** Asks only for Media/Data path, Memories photo path, master password, and safe Netplan static IP toggle. Deploys in 60s.
* **🛠️ Power User Mode:** Granular control over all ports, services, paths, and power schedules. Every optional field features a clear default badge and a 1-click **"Keep Default"** action.
* **🤖 AI Copilot Mode:** Hardware-tailored recommendations and a 1-click token-optimized diagnostic prompt (~300 tokens) for ChatGPT, Claude, Cursor, or Antigravity.

Once provisioning finishes, the wizard seamlessly transitions to your **Control Hub** command center (`http://<your-server-ip>:7575`)!

---

## 📚 Deep Dive Runbooks & Guides
* [Storage Architecture & 0 I/O Hardlinks](docs/STORAGE_AND_HARDLINKS.md)
* [Power Management & RTC Wake Self-Healing](docs/POWER_MANAGEMENT_RTCWAKE.md)
* [Networking: Tailscale Subnet Routing & Samba Shares](docs/NETWORKING_TAILSCALE_SAMBA.md)
* [Safe Netplan Static IP & SSH Safety Quirks](docs/NETPLAN_STATIC_IP_QUIRKS.md)
* [Docker File Permissions, PUID/PGID & UMASK](docs/DOCKER_PERMISSIONS_PUID_PGID.md)
* [Port Bindings, Network Mapping & Conflict Resolution](docs/PORT_BINDINGS_AND_CONFLICTS.md)
* [Hardware Acceleration (VAAPI / QSV) & Low-Power Quirks](docs/HARDWARE_ACCELERATION_VAAPI_QSV.md)
* [Low-Power CPU & Direct Play Optimization](docs/HASWELL_DIRECT_PLAY_GUIDE.md)
* [Gigabit LAN Diagnostics & Physical Link Auto-Negotiation](docs/GIGABIT_LAN_DIAGNOSTICS.md)
* [Master Verification & End-to-End Test Suite Report](docs/HOMELAB_VERIFICATION_AND_TEST_REPORT.md)
* [Control Hub Node Configuration Center & AI Copilot](docs/CONTROL_HUB_CONFIGURATION_CENTER.md)
* [Web GUI Setup Wizard Verification & Test Results](docs/SETUP_WIZARD_TEST_RESULTS.md)

---

## 📄 License
MIT License. Free to use, adapt, and build your own dream homelab!
