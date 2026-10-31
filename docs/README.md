# Homelab Blueprint - Documentation Hub & Runbook Portal 📚🧭

> Central engineering knowledge base, operational runbooks, architectural specifications, and hardware guides for the **Homelab Blueprint** monorepo.

---

## 📑 Table of Contents
1. [Documentation Architecture & Philosophy](#-documentation-architecture--philosophy)
2. [Role-Based Reading Paths](#-role-based-reading-paths)
3. [Master Runbook & Guide Catalog](#-master-runbook--guide-catalog)
   * [Foundation, Storage & Networking](#1-foundation-storage--networking)
   * [Hardware Acceleration & Power Management](#2-hardware-acceleration--power-management)
   * [Day-to-Day Operations & Control Hub](#3-day-to-day-operations--control-hub)
   * [AI Pairing & Automated Testing](#4-ai-pairing--automated-testing)
4. [Architecture Decision Records (ADRs)](#-architecture-decision-records-adrs)
5. [Component README Directory Map](#-component-readme-directory-map)
6. [Troubleshooting & Emergency Playbooks](#-troubleshooting--emergency-playbooks)

---

## 🧭 Documentation Architecture & Philosophy

This repository adheres to the **Diátaxis framework**, categorizing technical documentation into four distinct learning objectives:

```
                  PRACTICAL (Action-Oriented)
                              │
               Tutorials      │     How-To Guides
            (Getting Started) │   (Problem-Solving)
                              │
LEARNING ─────────────────────┼───────────────────── WORKING
(Acquisition)                 │                     (Application)
                              │
               Explanation    │       Reference
              (Architecture)  │     (Information)
                              │
                 THEORETICAL (Knowledge-Oriented)
```

1. **Tutorials (Getting Started):** Step-by-step onboarding walkthroughs for new clusters (`setup/README.md`).
2. **How-To Guides:** Goal-oriented execution recipes for specific tasks (e.g. configuring VAAPI/QSV transcode, deploying Tailscale).
3. **Reference:** Complete, authoritative specifications (e.g. port matrix, environment variables, permission standards).
4. **Explanation / Architecture:** Big-picture design principles (e.g. atomic hardlink storage hierarchy, ACPI S3 sleep economics).

---

## 👥 Role-Based Reading Paths

Find the most efficient entry point based on your current task:

```
┌───────────────────────────────────┬────────────────────────────────────────────────────────┐
│ Persona / Objective               │ Recommended Reading Path                               │
├───────────────────────────────────┼────────────────────────────────────────────────────────┤
│ 🚀 First-Time Deployer            │ 1. Root README.md                                      │
│    "I want to bootstrap my server"│ 2. setup/README.md                                     │
│                                   │ 3. docs/STORAGE_AND_HARDLINKS.md                       │
├───────────────────────────────────┼────────────────────────────────────────────────────────┤
│ 🛠️ System Administrator          │ 1. docs/PORT_BINDINGS_AND_CONFLICTS.md                 │
│    "I want to manage services,    │ 2. docs/NETPLAN_STATIC_IP_QUIRKS.md                    │
│     ports, power, and backups"    │ 3. docs/POWER_MANAGEMENT_RTCWAKE.md                    │
│                                   │ 4. system/README.md                                    │
├───────────────────────────────────┼────────────────────────────────────────────────────────┤
│ 🎬 Media & Hardware Enthusiast    │ 1. docs/HARDWARE_ACCELERATION_VAAPI_QSV.md             │
│    "I want 4K transcode & 0-I/O"  │ 2. docs/HASWELL_DIRECT_PLAY_GUIDE.md                   │
│                                   │ 3. apps/mediaserver/README.md                          │
├───────────────────────────────────┼────────────────────────────────────────────────────────┤
│ 🤖 AI Coding Assistant / Engineer │ 1. docs/AI_AGENT_INSTRUCTIONS.md                       │
│    "I want dense system context   │ 2. docs/adr/README.md                                  │
│     and test specifications"      │ 3. testing/README.md                                   │
└───────────────────────────────────┴────────────────────────────────────────────────────────┘
```

---

## 📚 Master Runbook & Guide Catalog

### 1. Foundation, Storage & Networking

* **[Storage Architecture & 0-I/O Hardlinks](STORAGE_AND_HARDLINKS.md)**
  * *Why it matters:* Explains how a single `/data` ext4 mount enables instantaneous, zero-disk-space hardlinks between qBittorrent and Radarr/Sonarr, preventing disk thrashing and duplicate storage.
* **[Docker Permissions: PUID, PGID & Umask](DOCKER_PERMISSIONS_PUID_PGID.md)**
  * *Why it matters:* Definitive guide to user mapping (`PUID=1000`, `PGID=1000`), `umask 002`, and avoiding `Permission Denied` errors across shared container volumes.
* **[Port Bindings & Network Matrix](PORT_BINDINGS_AND_CONFLICTS.md)**
  * *Why it matters:* Authoritative directory of all active TCP/UDP ports across the 13 homelab services, collision avoidance, and socket conflict prevention.
* **[Safe Netplan Static IP](NETPLAN_STATIC_IP_QUIRKS.md)**
  * *Why it matters:* Covers Ubuntu Netplan v2 configuration, YAML formatting quirks, and the essential 45-second auto-rollback command (`netplan try --timeout 45`) to prevent SSH lockout.
* **[Networking: Tailscale & Samba](NETWORKING_TAILSCALE_SAMBA.md)**
  * *Why it matters:* Tailscale mesh subnet routing for secure remote access without port forwarding, paired with Samba LAN shares (`MediaDrive` and `RootFS`).
* **[Gigabit LAN Diagnostics](GIGABIT_LAN_DIAGNOSTICS.md)**
  * *Why it matters:* Troubleshooting PHY auto-negotiation, bad Cat5e/Cat6 patch cables, and isolating 100 Mbps Ethernet link drops.

### 2. Hardware Acceleration & Power Management

* **[Hardware Acceleration (VAAPI & Intel QuickSync)](HARDWARE_ACCELERATION_VAAPI_QSV.md)**
  * *Why it matters:* Complete setup for Intel `/dev/dri` render nodes, group permissions (`render`/`video`), low-power tone mapping, and driver selection across Gen 7 to Gen 14 CPUs.
* **[Low-Power Direct Play Guide](HASWELL_DIRECT_PLAY_GUIDE.md)**
  * *Why it matters:* Optimization handbook for budget mini-PCs (Haswell Gen 4, Skylake, N100) to achieve 100% Direct Play and avoid transcoding bottlenecks.
* **[Power Management & RTC Wake](POWER_MANAGEMENT_RTCWAKE.md)**
  * *Why it matters:* Deep-dive into automated ACPI S3 Suspend-to-RAM (~1.2W) at midnight, CMOS hardware RTC wakeup alarms at 06:00 AM, and active download/SMB safety checks.

### 3. Day-to-Day Operations & Control Hub

* **[Control Hub Configuration Center](CONTROL_HUB_CONFIGURATION_CENTER.md)**
  * *Why it matters:* Architectural guide to the live node dashboard at `:7575`, real-time port polling, live `os.link` storage testing, and secret regeneration.
* **[Master Verification & Test Report](HOMELAB_VERIFICATION_AND_TEST_REPORT.md)**
  * *Why it matters:* Complete test documentation including 13 visual proof screenshots, risk matrices, and deployment verification artifacts.
* **[Early Setup Wizard Test Results](SETUP_WIZARD_TEST_RESULTS.md)**
  * *Why it matters:* Historical validation log of the zero-dependency onboarding wizard browser interactions and dry-run execution results.

### 4. AI Pairing & Automated Testing

* **[AI Agent Master Instructions](AI_AGENT_INSTRUCTIONS.md)**
  * *Why it matters:* High-density architectural cheatsheet tailored for LLMs and autonomous coding assistants (token-optimized, zero fluff).
* **[Master Testing Plan & Test Harness](../testing/README.md)**
  * *Why it matters:* End-to-end regression specifications, cross-platform hardware emulation guidelines, and GitHub Actions CI matrix documentation.

---

## 🏛️ Architecture Decision Records (ADRs)

Key architectural choices are recorded with their problem context and trade-offs in **[`docs/adr/`](adr/README.md)**:

* **[ADR-0001: Single ext4 Mount for Atomic 0-I/O Hardlinks](adr/0001-single-mount-atomic-hardlinks.md)**
* **[ADR-0002: Zero-Dependency Standard-Library-Only Setup Wizard](adr/0002-zero-dependency-setup-wizard.md)**
* **[ADR-0003: ACPI S3 Suspend-to-RAM with RTC Wake vs Continuous Idle](adr/0003-acpi-s3-sleep-guard-power-automation.md)**

---

## 🗺️ Component README Directory Map

Every primary module in this monorepo includes a dedicated, colocated `README.md` providing local architecture, environment flags, and component execution instructions:

```
├── README.md                                # Root Project Overview & Portal
├── ARCHITECTURE.md                          # Full Monorepo Architecture & Hardware Tiers
├── setup/README.md                          # Phase 1 Zero-Dependency Setup Wizard
├── apps/
│   ├── control-hub/README.md                # Cyber-HUD Dashboard & Host Telemetry Daemon
│   ├── mediaserver/README.md                # Docker Compose Media Stack (Jellyfin, *arrs, qBit)
│   ├── noodle-gallery/README.md             # Photo Cloud, PostgreSQL VectorChord & Face Recognition
│   ├── tv-updater/README.md                 # Smart TV Fleet ADB Wireless App Synchronizer
│   └── immich-face-xmp-exporter/README.md   # Non-Destructive Bidirectional Face XMP Sidecar Sync
├── system/README.md                         # Host Systemd Services, Cron Jobs & Sleep Daemons
└── testing/README.md                        # Master QA Verification Plan & CI Automation
```

---

## 🚨 Troubleshooting & Emergency Playbooks

| Symptom / Failure | Diagnostic Command | Remediation Guide |
| :--- | :--- | :--- |
| **Media takes 2x disk space / slow copy** | `ls -l /data/media/movies` (check link count) | [Storage & Hardlinks Guide](STORAGE_AND_HARDLINKS.md) |
| **Jellyfin 100% CPU on 4K playback** | `ls -l /dev/dri` & inspect Jellyfin logs | [Hardware Acceleration Guide](HARDWARE_ACCELERATION_VAAPI_QSV.md) |
| **Lost SSH access after static IP edit** | Wait 45s for `netplan try` auto-rollback | [Safe Netplan Guide](NETPLAN_STATIC_IP_QUIRKS.md) |
| **Permission Denied creating files in Docker** | `id` (verify PUID/PGID matches `1000:1000`) | [Docker Permissions Guide](DOCKER_PERMISSIONS_PUID_PGID.md) |
| **Server didn't sleep or woke unexpectedly** | `journalctl -u control-hub` & inspect sleep logs | [Power Management Guide](POWER_MANAGEMENT_RTCWAKE.md) |
| **Port conflict on server startup** | Run live port prober in Control Hub `:7575` | [Port Bindings Guide](PORT_BINDINGS_AND_CONFLICTS.md) |
| **Network speeds capped at 100 Mbps** | `ethtool <nic>` (check Speed & Duplex) | [Gigabit LAN Diagnostics](GIGABIT_LAN_DIAGNOSTICS.md) |

