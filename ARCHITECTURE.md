# Homelab System Architecture & Hardware Optimization 📐

> A production-engineered, hardware-agnostic self-hosted architecture designed to run on **any hardware**—from repurposed ultra-low-power laptops and mini-PCs (Intel Haswell / N100) to modern multi-core towers (Intel 12th-14th Gen, AMD Ryzen), ARM64 single-board computers (Raspberry Pi 5), and virtualized hypervisors (Proxmox, ESXi, Hyper-V).

---

## 1. Hardware-Agnostic Design & Dynamic Probing

The blueprint is built from the ground up to **auto-detect host hardware and dynamically adapt its orchestration, storage monitoring, and media playback pipelines**:

```
┌────────────────────────────────────────────────────────────────────────┐
│                   AUTOMATED HARDWARE PROBING ENGINE                    │
│                        (setup/config_core/system_prober.py)            │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
       ┌────────────────────────────┼────────────────────────────┐
       ▼                            ▼                            ▼
┌──────────────┐             ┌──────────────┐             ┌──────────────┐
│     CPU      │             │    MEMORY    │             │   STORAGE    │
│ Architecture │             │ Headroom &   │             │ Inode & Link │
│ & Low-Power  │             │ Swap Sizing  │             │ Verification │
└──────┬───────┘             └──────┬───────┘             └──────┬───────┘
       │                            │                            │
       ▼                            ▼                            ▼
┌──────────────┐             ┌──────────────┐             ┌──────────────┐
│  GPU Render  │             │   NETWORK    │             │ CONTROL HUB  │
│ Nodes (DRI)  │             │ NIC Link &   │             │ Real-Time    │
│ QSV vs Play  │             │ IP Gateway   │             │ HUD Display  │
└──────────────┘             └──────────────┘             └──────────────┘
```

### Probed Subsystems & Adaptive Logic:
1. **CPU & Instruction Architecture:**
   - Detects processor model, architecture (`x86_64`, `aarch64`), and core/thread count from `/proc/cpuinfo` and OS APIs.
   - Automatically classifies legacy or transcode-constrained processors (e.g. Intel Haswell, Celeron, Atom, Jasper Lake) to enforce **Direct Play CPU Protection Mode** (<1.5% CPU vs 100% transcode lock).
2. **RAM & Swap Scaling:**
   - Detects total physical memory and available headroom via `/proc/meminfo`.
   - Constrained hosts (<8 GiB RAM) receive conservative container buffer limits, scheduled AI/ML worker schedules, and swap headroom warnings.
3. **Hardware Acceleration & GPU Render Nodes:**
   - Inspects `/dev/dri/renderD128` (Intel QuickSync / VAAPI) and `nvidia-smi` presence.
   - If dedicated hardware acceleration is available, unlocks hardware transcoding in Jellyfin; otherwise defaults to safe Direct Play.
4. **Storage & Block Devices:**
   - Probes root (`/`) and data mount block devices (`nvme*`, `sd*`, `vd*`, `mmcblk*`) from `/proc/mounts` and `/proc/diskstats`.
   - Verifies filesystem single-mount compliance using live `os.link` inode checks before any downloaders launch.
5. **Network Interface & Link Negotiation:**
   - Probes active primary NIC (e.g. `eth0`, `enp3s0`, `eno1`, `wlan0`), negotiated link speed (`/sys/class/net/<iface>/speed`), and duplex state.

---

## 2. Tested Hardware Profiles & Baseline Reference

While designed for any hardware, the monorepo was rigorously stress-tested on an **ultra-low-power minimum baseline** to prove that self-hosting does not require expensive enterprise servers:

| Hardware Tier | Example Hardware | CPU / RAM Profile | Storage Layout | Power Draw (Active / Sleep) | Optimal Playback Mode |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Tier 1 (Tested Baseline)** | Repurposed Laptop / HP ProDesk Mini | Intel Core i3-4005U (2C/4T @ 1.70GHz, 15W TDP) &bull; 7.2 GiB DDR3 | 240GB SSD (OS) + 1TB HDD (Media) | **8W / 1.2W (S3)** | Direct Play Enforced |
| **Tier 2 (Modern Mini-PC)** | Beelink / Intel N100 / N200 / N305 | Intel Alder Lake-N (4C/4T @ 3.4GHz, 6W TDP) &bull; 16GB DDR5 | 512GB NVMe (OS) + 2TB SATA DAS | **6W / 1.0W (S3)** | Intel QuickSync (QSV) |
| **Tier 3 (Home Server / SFF)** | Dell OptiPlex / Custom Desktop | Intel Core i5-12400 / AMD Ryzen 5 5600G &bull; 32GB RAM | NVMe SSD + Dual HDD ZFS/Ext4 Pool | **22W / 2.0W (S3)** | Full HW Transcoding |
| **Tier 4 (ARM64 SBC)** | Raspberry Pi 5 / Rock 5B | Quad-Core Cortex-A76 &bull; 8GB LPDDR4X | NVMe PCIe Hat / USB 3.0 Storage | **5W / Standby** | Direct Play (Native MPV) |

---

## 3. Core Architectural Principles

### 1. Zero-Overhead Management (<25MB RAM)
Traditional homelab management suites (Homarr, Homepage, Portainer) run on heavy NodeJS or Electron stacks consuming hundreds of megabytes of RAM. Control Hub utilizes a widget-slice architecture in native Python Flask and Vanilla ES6 that maintains an idle footprint of **< 25 MB RAM** and **< 0.2% CPU**.

### 2. Single-Mount Ext4/XFS Atomic Hardlinks (0 Disk I/O)
All media ingestion containers (`qbittorrent`, `sonarr`, `radarr`, `bazarr`) share a unified root volume (`/mnt/hdd/data:/data`). Moving a completed download from `data/torrents/` into `data/media/` creates an instant inode pointer:
* **Disk I/O:** Exactly 0 MB written.
* **Storage Footprint:** Exactly 0 additional bytes used.
* **Latency:** <50 milliseconds.
* **Architecture Decision:** See [ADR-0001: Single ext4 Mount for Atomic 0-I/O Hardlinks](docs/adr/0001-single-mount-atomic-hardlinks.md).

### 3. Automated RTC S3 Sleep & Self-Healing
To prolong hardware lifespan and minimize electrical draw:
* System suspends to RAM (S3) at **12:00 AM** (configured via `/etc/cron.d/server-suspend`).
* System wakes automatically via hardware motherboard RTC alarm at **06:00 AM**.
* Active backup detection (`immich_backup_gdrive.sh`, `rclone`, `pg_dumpall`) automatically defers sleep until completion.
* Post-resume self-healing verifies network connectivity, resets Prowlarr backoff penalties, and triggers Arr library syncs.
* **Architecture Decision:** See [ADR-0003: ACPI S3 Suspend-to-RAM with RTC Wake](docs/adr/0003-acpi-s3-sleep-guard-power-automation.md).

### 4. Zero-Dependency Onboarding Bootstrap
The onboarding wizard runs on pure Python 3 standard library with zero external packages or pip installs:
* **Architecture Decision:** See [ADR-0002: Zero-Dependency Setup Wizard](docs/adr/0002-zero-dependency-setup-wizard.md).

### 5. ISP SNI DPI Bypass (Zero-Cost DNS Proxy)
Many regional Internet Service Providers block The Movie Database (TMDB) at the SNI/DNS level, preventing Jellyfin and Seerr from fetching movie posters and metadata. The architecture embeds `tmdb-interceptor.js`, intercepting blocked outbound calls in-memory and transparently rewriting them to clean Cloudflare DNS and mirrors without requiring commercial VPN subscriptions.

---

## 4. Documentation & Decision Index

* 📚 **[Master Documentation Hub & Runbook Portal](docs/README.md)**
* 🏛️ **[Architecture Decision Records (ADRs)](docs/adr/README.md)**
* ⚙️ **[Host System Daemons & Cron Services](system/README.md)**
* 🧪 **[Master Verification & Testing Plan](testing/README.md)**
