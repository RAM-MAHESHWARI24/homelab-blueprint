# Homelab Blueprint & Modular Sub-Repositories 🏠⚡

> A production-tested, low-power homelab blueprint featuring atomic media hardlinks, automated RTC wake power management, ISP SNI DPI bypasses, silent Android TV maintenance, and non-vendor-locked photo metadata tools.

[![Ubuntu](https://img.shields.io/badge/Ubuntu-26.04%20LTS-orange.svg)](https://ubuntu.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## 🏗️ Repository Architecture

This blueprint uses an **Umbrella Architecture** combining 4 decoupled, standalone sub-repositories:

```
                               ┌──────────────────────────────────────────────┐
                               │           homelab-blueprint (Parent)         │
                               │  • Complete end-to-end setup runbook         │
                               │  • Tailscale, ZeroTier & Samba configs       │
                               │  • RTCWake power management & self-healing   │
                               │  • System cron definitions & systemd units   │
                               └──────────────────────┬───────────────────────┘
                                                      │
          ┌───────────────────┬───────────────────────┼───────────────────────┐
          ▼                   ▼                       ▼                       ▼
 ┌──────────────────┐┌──────────────────┐┌──────────────────┐┌───────────────────────────┐
 │   control-hub    ││    tv-updater    ││ immich-xmp-tools ││    mediaserver-blueprint  │
 │  (Submodule 1)   ││  (Submodule 2)   ││  (Submodule 3)   ││       (Submodule 4)       │
 │ • Custom Web GUI ││ • ADB TV updater ││ • Face XMP side- ││ • Docker Compose stack    │
 │ • Dozzle v11 log ││ • DHCP discovery ││   car exporter   ││ • TMDB DPI SNI patch      │
 │ • Sleep guard    ││ • Zero TV RAM    ││ • Google Drive   ││ • Recyclarr profiles      │
 │ • Vitals/Network ││ • SmartTube / CS ││   sync pipeline  ││ • Webhook / Seerr listener│
 └──────────────────┘└──────────────────┘└──────────────────┘└───────────────────────────┘
```

### Modular Standalone Repositories

| Repository | Purpose | Key Tech |
| :--- | :--- | :--- |
| **[`control-hub`](submodules/control-hub)** | Lightweight (<25MB RAM) glassmorphism server dashboard | Python, Flask, ES6 Modules |
| **[`tv-updater`](submodules/tv-updater)** | Zero-overhead Android TV background ADB updater (SmartTube, CloudStream) | Python, Network ADB |
| **[`immich-face-xmp-exporter`](submodules/immich-face-xmp-exporter)** | Batch ExifTool MWG XMP sidecar generator & cloud sync pipeline | Python, ExifTool, Rclone |
| **[`mediaserver-blueprint`](submodules/mediaserver-blueprint)** | Media ingest pipeline with atomic hardlinks & TMDB ISP patch | Docker Compose, Jellyfin, Arr stack |

---

## 🚀 How to Clone & Use

### 1. Clone Entire Homelab Blueprint (With All Submodules)
```bash
git clone --recurse-submodules https://github.com/<your-username>/homelab-blueprint.git
```

### 2. Or Clone Only the Specific Component You Need
* **Just the Dashboard:**
  ```bash
  git clone https://github.com/<your-username>/control-hub.git
  ```
* **Just the Android TV Updater:**
  ```bash
  git clone https://github.com/<your-username>/tv-updater.git
  ```
* **Just the Immich Face Exporter:**
  ```bash
  git clone https://github.com/<your-username>/immich-face-xmp-exporter.git
  ```
* **Just the Media Pipeline:**
  ```bash
  git clone https://github.com/<your-username>/mediaserver-blueprint.git
  ```

---

## 📚 Deep Dive Guides
* [Storage Architecture & 0 I/O Hardlinks](docs/STORAGE_AND_HARDLINKS.md)
* [Power Management & RTC Wake Self-Healing](docs/POWER_MANAGEMENT_RTCWAKE.md)
* [Networking: Tailscale Subnet Routing & Samba](docs/NETWORKING_TAILSCALE_SAMBA.md)
* [Low-Power CPU & Direct Play Optimization](docs/HASWELL_DIRECT_PLAY_GUIDE.md)
* [Gigabit LAN Diagnostics & Physical Link Auto-Negotiation](docs/GIGABIT_LAN_DIAGNOSTICS.md)

---

## 📄 License
MIT License. Free to use and build your own dream homelab!
