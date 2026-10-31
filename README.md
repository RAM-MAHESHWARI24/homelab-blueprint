# Homelab Blueprint & All-in-One Monorepo 🏠⚡

> A production-tested, ultra-low-power homelab monorepo featuring **instant 0-I/O atomic media hardlinks**, **automated RTC-wake power management (1.2W S3 sleep)**, **ISP SNI DPI bypasses**, **silent Android TV maintenance**, **non-vendor-locked photo metadata tools**, and a **custom <25MB RAM dark glassmorphism dashboard with integrated AI Copilot**.

[![Ubuntu](https://img.shields.io/badge/Ubuntu-26.04%20LTS-orange.svg)](https://ubuntu.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Monorepo](https://img.shields.io/badge/Monorepo-All--in--One-success.svg)](#repository-layout)
[![Hardlinks](https://img.shields.io/badge/Hardlinks-Instant%200%20I%2FO-brightgreen.svg)](docs/STORAGE_AND_HARDLINKS.md)
[![Control Hub RAM](https://img.shields.io/badge/Control%20Hub%20RAM-%3C25MB-success.svg)](apps/control-hub/)
[![Automated Tests](https://img.shields.io/badge/Tests-100%25%20Passing-blue.svg)](setup/test_setup.py)

---

## 🌟 Why an All-in-One Monorepo?

Instead of juggling multiple scattered repositories, conflicting `.env` files, and fragile Git submodule commands, this repository contains **everything in one place**. A single clone provides the complete server orchestration suite, hardware optimization runbooks, custom dashboard daemon, automated TV updater, and media ingestion stack:

```
homelab-blueprint/
├── README.md                           # Master homelab overview & quickstart
├── AGENTS.md                           # AI Coding Agent Master Operating Standards & Rules
├── ARCHITECTURE.md                     # Deep technical architecture (storage, CPU, memory, power)
├── bootstrap.sh                        # 1-Line zero-dependency Ubuntu server installer
├── setup.sh                            # Local repository setup and wizard launcher
├── teardown.sh                         # Clean cluster uninstaller & host state restoration
├── .env.example                        # Unified server configuration template
├── docs/                               # Engineering runbooks, ADRs & visual test reports
│   ├── README.md                       # Master documentation hub & Diátaxis navigation portal
│   ├── adr/                            # Architecture Decision Records (ADRs)
│   │   ├── README.md                   # ADR index, status taxonomy, and contribution template
│   │   ├── 0001-single-mount-atomic-hardlinks.md
│   │   ├── 0002-zero-dependency-setup-wizard.md
│   │   └── 0003-acpi-s3-sleep-guard-power-automation.md
│   ├── STORAGE_AND_HARDLINKS.md        # Single ext4 mount atomic hardlink guide (0 disk I/O)
│   ├── POWER_MANAGEMENT_RTCWAKE.md     # S3 suspend (1.2W) & post-wake self-healing runbook
│   ├── NETWORKING_TAILSCALE_SAMBA.md   # Tailscale subnet routing & Samba dual shares
│   ├── NETPLAN_STATIC_IP_QUIRKS.md     # Safe Netplan rollback & SSH disconnection prevention
│   ├── DOCKER_PERMISSIONS_PUID_PGID.md # Linux file ownership, UMASK 002, and user mapping
│   ├── PORT_BINDINGS_AND_CONFLICTS.md  # Complete 13-service port allocation directory
│   ├── HARDWARE_ACCELERATION_VAAPI_QSV.md # Intel QuickSync, VAAPI /dev/dri render node guide
│   ├── HASWELL_DIRECT_PLAY_GUIDE.md    # Low-power CPU transcode protection & direct play
│   ├── GIGABIT_LAN_DIAGNOSTICS.md      # Ethernet link auto-negotiation & PHY diagnostics
│   ├── AI_AGENT_INSTRUCTIONS.md        # High-density token-optimized LLM guidelines
│   ├── CONTROL_HUB_CONFIGURATION_CENTER.md # Control Hub Settings modal & AI Copilot runbook
│   ├── SETUP_WIZARD_TEST_RESULTS.md    # Initial setup wizard verification & dry-run test
│   ├── HOMELAB_VERIFICATION_AND_TEST_REPORT.md # Master E2E verification report (13 visual proofs)
│   └── assets/                         # Full visual verification screenshot gallery
├── setup/                              # Zero-dependency Python 3 onboarding wizard (Port 8000)
│   ├── server.py                       # Pure standard-library HTTP server & REST API
│   ├── config_core/                    # System probing, secrets generator, Netplan manager
│   ├── static/                         # High-DPI dark glassmorphism onboarding interface
│   ├── test_setup.py                   # Automated verification test suite
│   └── README.md                       # Setup wizard architectural documentation
├── testing/                            # Master quality assurance, VM sandboxes & CI/CD
│   └── README.md                       # Full testing plan, hardware matrix, and DoD
├── system/                             # Host OS automation & configurations
│   ├── README.md                       # Host daemons, sleep automation & cron architecture
│   ├── cron.d/                         # Template cron definitions (suspend, backup, updates)
│   ├── systemd/                        # Systemd unit files (Control Hub background daemon)
│   ├── power/                          # Suspend, RTC wake, and ML container schedule scripts
│   ├── networking/                     # Tailscale forwarding & Samba shares (smb.conf)
│   └── maintenance/                    # Automated Watchtower updater with log rotation
└── apps/                               # Real application source trees & pipelines
    ├── control-hub/                    # Custom Python/Flask command center (<25MB RAM, Port 7575)
    ├── tv-updater/                     # Zero-overhead background Android TV ADB updater
    ├── noodle-gallery/                 # High-performance photo & video cloud with VectorChord search
    ├── immich-face-xmp-exporter/       # Non-destructive face-to-XMP sidecar exporter & cloud sync
    └── mediaserver/                    # Complete Docker Compose media stack with TMDB DPI patch
```

---

## 📦 What's Inside

| Module | Location | Purpose | Key Tech | RAM Footprint |
| :--- | :--- | :--- | :--- | :--- |
| **Control Hub** | [`apps/control-hub/`](apps/control-hub/) | Active command center, hardware telemetry, node config & AI Copilot | Python, Flask, Vanilla ES6 | **< 25 MB** |
| **CleanYourTV** | [`apps/tv-updater/`](apps/tv-updater/) | Silent background Android TV ADB app updater | Python, Network ADB (Port 5555) | **< 5 MB** |
| **Noodle Gallery** | [`apps/noodle-gallery/`](apps/noodle-gallery/) | High-performance photo cloud with vector search | Open-Noodle Gallery, PostgreSQL, Valkey | Scheduled |
| **Immich XMP Tools** | [`apps/immich-face-xmp-exporter/`](apps/immich-face-xmp-exporter/) | Batch ExifTool face-to-XMP sidecar generator & cloud backup | Python, ExifTool, Rclone | On-Demand |
| **Media Pipeline** | [`apps/mediaserver/`](apps/mediaserver/) | Jellyfin, Arr stack, atomic hardlinks & TMDB ISP patch | Docker Compose, Jellyfin, Arr suite | Containerized |
| **Setup Wizard** | [`setup/`](setup/) | Zero-dependency onboarding wizard with Safe Netplan rollback | Python 3 Standard Library | Standby |

---

## ⚡ Two-Phase Operational Architecture

This repository is engineered around a clean lifecycle separation:
1. **Phase 1: Day 0 Onboarding & Provisioning Wizard** (`http://<server-ip>:8000`)
2. **Phase 2: Day 1+ Command Center & Live Configuration Hub** (`http://<server-ip>:7575`)

```
┌────────────────────────────────────────────────────────────────────────┐
│  PHASE 1: Zero-Dependency Onboarding Wizard (Port 8000)                │
│  • Express Mode (60s setup) or Power User Mode                         │
│  • Atomic os.link filesystem inode validation                          │
│  • Safe Netplan static IP test with auto-rollback                      │
│  • Dry-run simulation mode (zero host disruption)                      │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Automated handoff
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│  PHASE 2: Control Hub Command Center & Management Daemon (Port 7575)   │
│  • Sleep Guard hero card with dynamic process-aware deferral           │
│  • Non-blocking real-time Rx/Tx network bandwidth sampling             │
│  • Settings Modal: Storage paths, 13-service port matrix, secrets gen  │
│  • AI Copilot Modal: Hardware specs & ~300-token prompt exporter       │
│  • Dozzle 12-char hex Docker ID container log streamer                 │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 🚀 Phase 1: Quickstart & Automated Onboarding (Port 8000)

Deploy your homelab on a fresh Ubuntu Server in under 60 seconds with our zero-dependency Web GUI onboarding wizard.

### Option A: 1-Line Automated Bootstrap (Fastest)
Run this single command in your Ubuntu Server terminal:
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
```
👉 http://<your-server-ip>:8000   (accessible from any laptop, phone, or tablet on your LAN)
```

### The Three Onboarding Modes:
* **⚡ Express Mode ("Least Setup"):** Asks only for Media/Data path, Memories photo path, master password, and safe Netplan static IP toggle. Deploys in 60s.
* **🛠️ Power User Mode:** Granular control over all ports, services, paths, and power schedules. Every optional field features a clear default badge and a 1-click **"Keep Default"** action.
* **🤖 AI Copilot Mode:** Hardware-tailored recommendations and a 1-click token-optimized diagnostic prompt (~300 tokens) for ChatGPT, Claude, Cursor, or Antigravity.

| Express Mode Verification | Power User Granular Setup |
| :---: | :---: |
| ![Express Mode](docs/assets/setup-wizard/express_mode_stage2_verified.png) | ![Power User Mode](docs/assets/setup-wizard/power_user_stage1_network_storage.png) |

---

## 🖥️ Phase 2: Day-to-Day Node Management in Control Hub (Port 7575)

Once provisioned, your server is managed around the clock via **Control Hub** at `http://<your-server-ip>:7575`.

![Control Hub Header](docs/assets/control-hub/hub_header_settings_ai.png)

### ⚙️ Integrated Node Configuration Center
Clicking **⚙️ Settings** in the dashboard header opens a 5-tab live configuration modal:
* **Storage & Atomic Hardlinks:** Run live `os.link` inode verification tests directly against your disks to guarantee instant, 0-I/O hardlinks.
* **13-Service Port Matrix:** Live socket prober scans all homelab ports in real time (Jellyfin `8096`, Seerr `5055`, Sonarr `8989`, Radarr `7878`, Prowlarr `9696`, Immich `2283`, etc.).
* **Security & Credentials:** 1-Click CSPRNG generator for high-entropy alphanumeric passwords and 32-character API keys.
* **Safe Netplan Static IP:** Inspect active network interfaces, preview Netplan YAML, and apply changes safely with `netplan try --timeout 45`.
* **Wizard Fast Launcher:** Re-open the zero-dependency onboarding wizard on port `8000` with 1 click.

| Inode Hardlink Verification | 13-Service Port Matrix & Prober |
| :---: | :---: |
| ![Hardlink Test](docs/assets/control-hub/hub_settings_hardlink_test.png) | ![Port Matrix](docs/assets/control-hub/hub_settings_port_matrix.png) |

### 🤖 Built-in AI Copilot
Clicking **🤖 AI Copilot** in the header opens a dedicated drawer for operators working with AI coding assistants:
* Gathers live host CPU model, core/thread count, physical memory, active IP, and `/dev/dri` GPU render node status.
* 1-Click **"📋 Copy AI Prompt"** exports a dense, token-optimized context prompt (~300 tokens) ready to paste into ChatGPT, Claude, Cursor, or Antigravity.
* Direct links to offline markdown engineering runbooks for zero-overhead troubleshooting.

![AI Copilot Drawer](docs/assets/control-hub/hub_ai_copilot_diagnostics.png)

---

## 🧹 Clean Teardown & Uninstallation

If you ever need to decommission or move your installation, run the clean uninstaller:

```bash
# Safe interactive uninstallation (preserves media, photos & databases)
sudo ./teardown.sh

# Non-interactive uninstallation
sudo ./teardown.sh -y

# Simulation mode (shows what would be removed without making changes)
./teardown.sh --dry-run
```

* **What it stops & cleans:** Stops all Docker Compose stacks, disables & removes `control-hub.service`, removes cron entries from `/etc/cron.d/`, and removes helper binaries.
* **Data Safety:** By default, all media files (`/mnt/hdd/data`), photos, and databases are **safely preserved on disk**. Use `--purge-data` only if you wish to wipe app configurations.

---

## 🧪 Verification & Automated Test Suite

We maintain strict verification standards to guarantee that deployments never break host networking, corrupt permissions, or trigger storage bottlenecks:

```bash
# Run the automated setup wizard test suite
python3 setup/test_setup.py
```

### Verified Test Matrix:
* **✓ Healthcheck Endpoint (`GET /api/health`):** 100% responsiveness.
* **✓ Hardware Auto-Probing (`GET /api/probe`):** Accurately detects CPU cores, memory, NICs, and physical disks.
* **✓ Atomic Hardlink Probe (`POST /api/verify/hardlink`):** Validates single-mount inode compatibility in <50ms.
* **✓ Cryptographic Secrets (`POST /api/secrets/generate`):** High-entropy passwords and API keys.
* **✓ Dry-Run Pipeline (`POST /api/deploy` with `dry_run=true`):** Full end-to-end simulation writing isolated configs to `setup/dry_run_preview/` without touching production files.
* **✓ UI Visual Verification:** All 13 test stage screenshots documented in [`docs/HOMELAB_VERIFICATION_AND_TEST_REPORT.md`](docs/HOMELAB_VERIFICATION_AND_TEST_REPORT.md).

---

## 📚 Master Documentation Hub & Engineering Runbooks

Comprehensive technical documentation covering every homelab subsystem (see **[docs/README.md](docs/README.md)** for full Diátaxis navigation):

| Document | Description |
| :--- | :--- |
| **[Master Documentation Hub](docs/README.md)** | Central documentation portal, Diátaxis role-based paths & runbook index |
| **[Architecture Decision Records (ADRs)](docs/adr/README.md)** | Immutable historical log of core architectural choices and trade-offs |
| **[Host Daemons, Sleep & Cron](system/README.md)** | Host-level systemd service, ACPI S3 suspend script & cron automation |
| **[Master Verification & Test Report](docs/HOMELAB_VERIFICATION_AND_TEST_REPORT.md)** | Full end-to-end verification report with 13 visual proofs & risk analysis |
| **[Control Hub Configuration Center](docs/CONTROL_HUB_CONFIGURATION_CENTER.md)** | Deep dive into the live dashboard configuration drawer & AI Copilot |
| **[Storage Architecture & 0-I/O Hardlinks](docs/STORAGE_AND_HARDLINKS.md)** | Single ext4 mount atomic hardlink guide (0 disk space, 0 I/O load) |
| **[Power Management & RTC Wake](docs/POWER_MANAGEMENT_RTCWAKE.md)** | S3 suspend (1.2W) at midnight, 06:00 AM RTC wake & self-healing |
| **[Networking: Tailscale & Samba](docs/NETWORKING_TAILSCALE_SAMBA.md)** | Tailscale subnet routing & Samba dual shares (`MediaDrive`, `RootFS`) |
| **[Safe Netplan Static IP](docs/NETPLAN_STATIC_IP_QUIRKS.md)** | Rollback mechanics (`netplan try --timeout 45`) & SSH safety |
| **[Docker Permissions & PUID/PGID](docs/DOCKER_PERMISSIONS_PUID_PGID.md)** | Linux file permissions, user mapping (`1000:1000`), and `UMASK=002` |
| **[Port Bindings & Network Matrix](docs/PORT_BINDINGS_AND_CONFLICTS.md)** | Directory of all 13 active ports and socket collision handling |
| **[Hardware Acceleration (VAAPI/QSV)](docs/HARDWARE_ACCELERATION_VAAPI_QSV.md)** | Intel QuickSync, `/dev/dri` render node permissions & drivers |
| **[Low-Power CPU & Direct Play](docs/HASWELL_DIRECT_PLAY_GUIDE.md)** | Haswell i3 / low-power CPU optimization & direct play enforcement |
| **[Gigabit LAN Diagnostics](docs/GIGABIT_LAN_DIAGNOSTICS.md)** | Ethernet auto-negotiation, PHY diagnostics, and Cat6 verification |
| **[AI Agent Master Instructions](docs/AI_AGENT_INSTRUCTIONS.md)** | High-density architectural cheatsheet for AI coding agents |
| **[AI Agent Operating Standards](AGENTS.md)** | Master engineering guidelines: coding standards, doc rules & test gates |
| **[Standards & Maturity Model](docs/STANDARDS_AND_MATURITY_MODEL.md)** | Evaluation against industry specs (SemVer, CIS, 12-Factor, OpenAPI) & roadmap |
| **[Setup Wizard Test Results](docs/SETUP_WIZARD_TEST_RESULTS.md)** | Early browser test validation and dry-run execution results |

---

## 💻 Universal Hardware Support & Dynamic Probing

The Homelab Blueprint is engineered to be **hardware-agnostic**: it runs out-of-the-box on **any hardware** and dynamically detects its host environment to optimize power, storage, and media transcoding:

* **Automatic Hardware Detection:** Both the Day 0 Setup Wizard (`port 8000`) and the Day 1 Control Hub (`port 7575`) dynamically probe host CPU model, core/thread count, physical memory headroom, active network interfaces, and storage block devices (`/dev/nvme*`, `/dev/sd*`, `/dev/vd*`).
* **Adaptive Playback Mode:** On legacy or transcode-constrained CPUs (Haswell, Celeron, Atom, N100), the system automatically enforces **Direct Play** (<1.5% CPU vs 100% transcode lock). On modern Intel/AMD/NVIDIA systems, GPU acceleration (`/dev/dri/renderD128`, NVENC) is unlocked.
* **Tested Hardware Profiles:**
  * **Tier 1 (Tested Minimum Baseline):** Repurposed laptop / Intel 4th-Gen Haswell (e.g. i3-4005U / i5-4200U), 8GB DDR3 RAM, 240GB SSD + 1TB HDD. Idle draw: **~8W daytime, 1.2W sleep**.
  * **Tier 2 (Modern Mini-PC):** Intel Alder Lake-N (N100 / N200 / N305), 16GB DDR5 RAM, NVMe SSD + USB3/SATA DAS. Idle draw: **~6W daytime, 1.0W sleep**.
  * **Tier 3 (Small Form Factor / Tower):** Intel 8th-14th Gen Core i3/i5/i7 or AMD Ryzen SFF PC, 16-64GB RAM, NVMe + multi-HDD pool.
  * **Tier 4 (ARM64 SBCs & VMs):** Raspberry Pi 5 / Rock 5B, Proxmox VE, ESXi, or Hyper-V virtual appliances.

---

## 📄 License

MIT License. Free to use, adapt, and build your own dream homelab!
