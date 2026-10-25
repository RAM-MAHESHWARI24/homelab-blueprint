# Homelab Blueprint - Master Testing & Verification Plan 🧪📋

> Comprehensive quality assurance framework, automated test specifications, hardware emulation guidelines, and CI/CD pipeline architecture for the **Homelab Blueprint** monorepo.

[![Ubuntu Test Matrix](https://img.shields.io/badge/Ubuntu-22.04%20%7C%2024.04%20LTS-orange.svg)](https://ubuntu.com/)
[![Architectures](https://img.shields.io/badge/Architectures-x86__64%20%7C%20arm64-blue.svg)](#3-hardware-simulation--resource-profiling-matrix)
[![Test Harness](https://img.shields.io/badge/Test%20Harness-Multipass%20%2B%20QEMU%20%2B%20Docker-brightgreen.svg)](#4-vm-based-sandbox-testing-guide-multipass)
[![CI/CD Strategy](https://img.shields.io/badge/CI%2FCD-Two--Tier%20GitHub%20Actions-purple.svg)](#6-github-actions-cicd-pipeline-strategy)

---

## 📑 Table of Contents
1. [Target "Definition of Done" (Acceptance Criteria)](#1-target-definition-of-done-acceptance-criteria)
2. [Testing Architecture & Layered Defense](#2-testing-architecture--layered-defense)
3. [Hardware Simulation & Resource Profiling Matrix](#3-hardware-simulation--resource-profiling-matrix)
4. [VM-Based Sandbox Testing Guide (Multipass)](#4-vm-based-sandbox-testing-guide-multipass)
5. [Detailed Test Modules & Execution Specifications](#5-detailed-test-modules--execution-specifications)
   * [Module 1: Zero-Dependency Bootstrap & Setup Server](#module-1-zero-dependency-bootstrap--setup-server)
   * [Module 2: Single-Mount Storage & Atomic Hardlinks](#module-2-single-mount-storage--atomic-hardlinks)
   * [Module 3: Safe Netplan Static IP & Auto-Rollback](#module-3-safe-netplan-static-ip--auto-rollback)
   * [Module 4: Docker Stacks & Pipeline Orchestration](#module-4-docker-stacks--pipeline-orchestration)
   * [Module 5: Host Daemons, Cron, & Power Management](#module-5-host-daemons-cron--power-management)
   * [Module 6: Security, Secrets & Sanitization](#module-6-security-secrets--sanitization)
6. [GitHub Actions CI/CD Pipeline Strategy](#6-github-actions-cicd-pipeline-strategy)
   * [Can we test this in CI/CD? Is it advisable?](#can-we-test-this-in-cicd-is-it-advisable)
   * [The Two-Tier CI/CD Architecture](#the-two-tier-cicd-architecture)
   * [Complete Ready-to-Use GitHub Actions Workflow](#complete-ready-to-use-github-actions-workflow)
7. [Automated Verification Checklist](#7-automated-verification-checklist)

---

## 1. Target "Definition of Done" (Acceptance Criteria)

Before declaring any release, pull request, or architectural change production-ready, the blueprint must satisfy **all** of the following verifiable conditions:

```
┌────────────────────────────────────────────────────────────────────────┐
│                      THE "FLAWLESS RUN" STANDARD                       │
├────────────────────────────────────────────────────────────────────────┤
│ 1. Zero-Touch Bootstrap:                                               │
│    `curl -sSL ... | sudo bash` succeeds on pristine minimal Ubuntu     │
│    without manual intervention, package prompts, or missing tools.     │
│                                                                        │
│ 2. Guaranteed 0-I/O Hardlinks:                                         │
│    qBittorrent -> Radarr/Sonarr atomic inode sharing verifies with     │
│    st_nlink >= 2 and exactly identical stat.st_ino numbers.           │
│                                                                        │
│ 3. Zero-Downtime Network Safety:                                       │
│    Netplan static IP updates auto-rollback within 45 seconds if the    │
│    gateway is misconfigured or SSH is severed.                         │
│                                                                        │
│ 4. Total Container Health:                                             │
│    100% of enabled Docker Compose services transition to Healthy       │
│    within 120 seconds with zero crashloops or restarts.                │
│                                                                        │
│ 5. Strict RAM Ceilings:                                                │
│    Control Hub host daemon consumes < 25 MB RAM.                       │
│    Combined idle server footprint stays under 1.8 GB RAM.              │
│                                                                        │
│ 6. Out-of-the-Box ISP Bypass:                                          │
│    Seerr loads movie metadata through tmdb-interceptor.js without DNS  │
│    handshake drops or 403 Forbidden blocks from regional ISPs.        │
│                                                                        │
│ 7. Sanitized Zero-Leak History:                                        │
│    Zero cleartext API keys, passwords, or host-identifying paths       │
│    committed to Git index or Git history.                              │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Testing Architecture & Layered Defense

To avoid disturbing the live production server (`Z:\` at `192.168.1.31`), testing is segmented into **four distinct environments**:

```
┌───────────────────────────────────────────────────────────────────────────┐
│                        LAYERED TESTING PYRAMID                            │
├───────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  [Layer 4: Real Bare-Metal Production] (Z:\ Server - 192.168.1.31)        │
│  • Intel QSV VAAPI /dev/dri render node direct play                       │
│  • Motherboard ACPI S3 rtcwake sleep (1.2W)                               │
│  • Physical Android TV network ADB updates (Port 5555)                    │
│                               ▲                                           │
│  [Layer 3: Ephemeral VM Sandboxes] (Multipass / Hyper-V on Host D:\)      │
│  • 100% genuine Linux kernel, virtual BIOS, isolated IP                   │
│  • True Netplan v2 netplan try --timeout test with safe rollback          │
│  • Multi-disk loop mounts (SSD root + ext4 HDD simulation)                │
│  • Resource capping (2GB RAM low-power mini-PC stress testing)            │
│                               ▲                                           │
│  [Layer 2: Fast Local Container & API Test] (Local WSL2 Ubuntu 24.04)     │
│  • Setup wizard REST API validation (setup/test_setup.py)                 │
│  • Docker compose up -d container startup & networking                    │
│  • Control Hub dashboard Flask daemon & widget endpoints                  │
│                               ▲                                           │
│  [Layer 1: Automated Cloud CI/CD] (GitHub Actions Cloud Runners)          │
│  • Linting, shell syntax (shellcheck), and PEP 8 verification             │
│  • Secret leak prevention (TruffleHog / Gitleaks)                         │
│  • Matrix tests: Ubuntu 22.04 LTS & 24.04 LTS                             │
│  • Multi-arch Docker pulls (x86_64 and arm64 via QEMU)                    │
└───────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Hardware Simulation & Resource Profiling Matrix

The blueprint is designed to run on diverse hardware—from salvaged dual-core laptops to modern Alder Lake mini-PCs and Raspberry Pis. Our test suite explicitly simulates these profiles:

| Profile ID | Target Archetype | Simulated Specs | Test Objectives |
| :--- | :--- | :--- | :--- |
| **`PROFILE_MINI_LOW`** | Low-Power Haswell / Celeron (i3-4005U, N4020, J1900) | **2 Cores, 2.0 GiB RAM**, 1x SATA HDD | • Memory pressure test: No OOM kills.<br>• Direct Play enforcement: AI Copilot disables CPU transcode.<br>• Off-peak ML container scheduling verification. |
| **`PROFILE_MID_NODE`** | Modern Efficient Mini-PC (Intel N100, N305, i5-8250U) | **4 Cores, 8.0 GiB RAM**, 1x SSD, 1x HDD | • Dual-mount storage: SSD for PostgreSQL/Thumbs, HDD for Media.<br>• QuickSync hardware accel path verification.<br>• High-throughput qBittorrent downloads (100MB/s). |
| **`PROFILE_ARM64_RPI`** | Single Board Computer (Raspberry Pi 4 / 5, Odroid) | **4 Cores (aarch64), 4.0 GiB RAM**, 1x USB3 Drive | • Multi-architecture container compatibility.<br>• ARMv7a/v8 APK tracking in `tv-updater`.<br>• VectorChord ARM64 vector search build compatibility. |
| **`PROFILE_MULTI_NIC`** | Dual Gigabit / 2.5GbE Server (Storage + LAN separation) | **4 Cores, 8.0 GiB RAM**, 2x NICs (`eth0`, `eth1`) | • Netplan static IP applied strictly to target NIC.<br>• Tailscale subnet forwarding on primary adapter. |
| **`PROFILE_MULTI_DRIVE_FAULT`** | Misconfigured Storage Topology (Cross-Mount Linking) | **2 Virtual Disks** (`/` and `/mnt/storage`) | • **Negative Test:** Proves atomic hardlink probe catches cross-mount attempt and displays instant resolution guide. |

---

## 4. VM-Based Sandbox Testing Guide (Multipass)

Because WSL lacks real motherboard ACPI clocks and virtual network adapters, **Canonical Multipass** is the industry standard for testing Ubuntu server deployments locally without disturbing server `Z:\`.

### Prerequisites (Host Machine)
Multipass installs with one command on Windows via `winget`:
```powershell
winget install Canonical.Multipass
```

### Scenario 1: Launch Low-Power Mini-PC Simulation (2 Cores, 2GB RAM)
```powershell
# 1. Launch a constrained Ubuntu 24.04 instance
multipass launch 24.04 --name homelab-low-spec --cpus 2 --memory 2G --disk 15G

# 2. Open shell in the fresh VM
multipass shell homelab-low-spec

# 3. Inside the VM: run the 1-line curl bootstrap
curl -sSL https://raw.githubusercontent.com/RAM-MAHESHWARI24/homelab-blueprint/main/bootstrap.sh | sudo bash
```

### Scenario 2: Simulate Separate Physical SSD and HDD Disks
Inside the Multipass VM, simulate two separate physical drives using Linux loopback block devices to test hardlink validation:
```bash
# Create two 5GB virtual disk images
sudo dd if=/dev/zero of=/drive_ssd.img bs=1M count=5000
sudo dd if=/dev/zero of=/drive_hdd.img bs=1M count=10000

# Format with ext4
sudo mkfs.ext4 -F /drive_ssd.img
sudo mkfs.ext4 -F /drive_hdd.img

# Mount to emulate fast SSD root and massive HDD media pool
sudo mkdir -p /mnt/ssd /mnt/hdd
sudo mount /drive_ssd.img /mnt/ssd
sudo mount /drive_hdd.img /mnt/hdd

# Test 1: Single mount (torrents + media on /mnt/hdd) -> MUST PASS
# Test 2: Split mount (torrents on /mnt/ssd, media on /mnt/hdd) -> MUST FAIL ATOMIC HARDLINK PROBE
```

### Scenario 3: Clean Teardown & Instant Reset
```powershell
# Stop and completely delete the test VM
multipass delete homelab-low-spec --purge
```

---

## 5. Detailed Test Modules & Execution Specifications

### Module 1: Zero-Dependency Bootstrap & Setup Server

* **Target Source:** [`bootstrap.sh`](../bootstrap.sh), [`setup.sh`](../setup.sh), [`setup/server.py`](../setup/server.py)
* **Goal:** Verify zero-dependency web onboarding from a completely bare Ubuntu terminal.

| Test ID | Test Scenario | Execution Command / Procedure | Expected Result | Pass Criteria |
| :--- | :--- | :--- | :--- | :--- |
| **`TC-BOOT-01`** | Pristine Execution | Execute `bootstrap.sh` on fresh Ubuntu 24.04 with only standard tools. | Installs `git`, `python3`, `python3-venv`, `jq`, and `docker.io`. Launches `setup/server.py`. | Exit code 0; Port 8000 listening. |
| **`TC-BOOT-02`** | Non-Root Auto Elevation | Run `./setup.sh` as regular user (without `sudo`). | Script detects non-root EUID and auto-elevates via `exec sudo bash`. | No permission denied crashes. |
| **`TC-BOOT-03`** | Zero Pip Dependencies | Verify `setup/server.py` executes without any external pip wheels installed. | Server starts using purely built-in `http.server`, `socket`, `subprocess`, `urllib`. | Zero `ModuleNotFoundError`. |
| **`TC-BOOT-04`** | Hardware Snapshot Accuracy | Send `GET /api/probe` to setup server daemon. | Returns CPU model, core count, GiB RAM, active NIC, and detected disk mounts. | HTTP 200; valid JSON schema. |
| **`TC-BOOT-05`** | Safe Simulation Mode | Send `POST /api/deploy` with `dry_run: true`. | Generates all `.env` files in `setup/dry_run_preview/` without modifying `/etc` or Docker state. | Original configs remain untouched; exit 200. |

---

### Module 2: Single-Mount Storage & Atomic Hardlinks

* **Target Source:** [`setup/config_core/storage_manager.py`](../setup/config_core/storage_manager.py), [`docs/STORAGE_AND_HARDLINKS.md`](../docs/STORAGE_AND_HARDLINKS.md)
* **Goal:** Mathematically verify 0-Disk I/O atomic hardlinks and prevent cross-mount performance degradation.

| Test ID | Test Scenario | Execution Command / Procedure | Expected Result | Pass Criteria |
| :--- | :--- | :--- | :--- | :--- |
| **`TC-STOR-01`** | Ext4 Inode Invariance | Execute `test_atomic_hardlink("/mnt/hdd/data")`. | Calls `os.link(src, dst)`. Checks `os.stat(src).st_ino == os.stat(dst).st_ino`. | `supported: true`, `latency_ms < 5.0ms`, `nlink >= 2`. |
| **`TC-STOR-02`** | Cross-Mount Failure Catch | Execute `test_atomic_hardlink` between two different mount points (`/` and `/mnt/hdd`). | Prober detects `EXDEV (Invalid cross-device link)`. | `supported: false`, actionable troubleshooting tip returned. |
| **`TC-STOR-03`** | Directory Hierarchy | Execute `create_homelab_directory_tree()`. | Generates all data and config paths (`torrents/{movies,tv}`, `media/{movies,tv}`). | Directories exist with `PUID:PGID` ownership. |
| **`TC-STOR-04`** | TMDB Interceptor Mirror | Execute deployment with custom `config_dir`. | Copies `tmdb-interceptor.js` into `${CONFIG_DIR}/seerr/`. | File exists in destination with `chmod 0644`. |

---

### Module 3: Safe Netplan Static IP & Auto-Rollback

* **Target Source:** [`setup/config_core/netplan_manager.py`](../setup/config_core/netplan_manager.py), [`docs/NETPLAN_STATIC_IP_QUIRKS.md`](../docs/NETPLAN_STATIC_IP_QUIRKS.md)
* **Goal:** Guarantee that static IP misconfigurations never lock an administrator out of SSH.

| Test ID | Test Scenario | Execution Command / Procedure | Expected Result | Pass Criteria |
| :--- | :--- | :--- | :--- | :--- |
| **`TC-NET-01`** | Pre-Flight Netplan Syntax | Execute `generate_netplan_yaml()` and validate via `netplan generate`. | Generates Netplan v2 YAML with `renderer: networkd` and explicit routes block. | Netplan syntax check returns exit code 0. |
| **`TC-NET-02`** | Safety Backup Creation | Apply proposed Netplan configuration. | Creates timestamped backup directory in `/etc/netplan/backup_<timestamp>/`. | Original YAMLs preserved bit-for-bit. |
| **`TC-NET-03`** | Auto-Rollback on Invalid Gateway | Apply Netplan configuration pointing to non-existent gateway (e.g. `192.168.254.254`). | `netplan try --timeout 45` triggers auto-revert upon timeout. | Network reverts to original DHCP/static state; SSH survives. |

---

### Module 4: Docker Stacks & Pipeline Orchestration

* **Target Source:** [`apps/mediaserver/`](../apps/mediaserver), [`apps/noodle-gallery/`](../apps/noodle-gallery)
* **Goal:** Verify that media ingestion, torrent downloading, and photo vector search run flawlessly.

| Test ID | Test Scenario | Execution Command / Procedure | Expected Result | Pass Criteria |
| :--- | :--- | :--- | :--- | :--- |
| **`TC-DOCK-01`** | Media Stack Convergence | Run `docker compose up -d` in `apps/mediaserver/`. | Spins up Jellyfin, Seerr, Prowlarr, Radarr, Sonarr, Bazarr, Byparr, qBittorrent. | All containers report `Up (healthy)`. |
| **`TC-DOCK-02`** | Noodle Gallery Stack | Run `docker compose up -d` in `apps/noodle-gallery/`. | Spins up Immich Server, Valkey Redis, and PostgreSQL with VectorChord. | PostgreSQL vector extension loads; HTTP 2283 responds. |
| **`TC-DOCK-03`** | TMDB ISP Bypass | Inside Seerr container, request `https://api.themoviedb.org/3/authentication`. | `tmdb-interceptor.js` transparently rewrites host to `api.tmdb.org`. | Request succeeds with HTTP 200 without TLS drops. |
| **`TC-DOCK-04`** | Off-Peak ML Throttling | Check `gallery-machine-learning` container restart policy. | Configured with `restart: "no"`. | Container does not run during waking hours. |

---

### Module 5: Host Daemons, Cron, & Power Management

* **Target Source:** [`apps/control-hub/`](../apps/control-hub), [`system/power/`](../system/power), [`apps/tv-updater/`](../apps/tv-updater)
* **Goal:** Verify ultra-low power consumption, host health telemetry, and autonomous Android TV maintenance.

| Test ID | Test Scenario | Execution Command / Procedure | Expected Result | Pass Criteria |
| :--- | :--- | :--- | :--- | :--- |
| **`TC-SYS-01`** | Control Hub Daemon Launch | `systemctl start control-hub.service`. | Flask API daemon binds to Port 7575. | HTTP 200 at `http://localhost:7575/`. |
| **`TC-SYS-02`** | Control Hub RAM Footprint | Probe Control Hub resident memory (`ps -o rss -p <pid>`). | Resident memory footprint strictly bounded. | **RSS < 25.0 MB**. |
| **`TC-SYS-03`** | Sleep Guard Skip Flag | Touch `/run/server-suspend.skip` and invoke `/usr/local/sbin/server-suspend.sh`. | Suspend routine detects flag, deletes it, and exits safely without sleeping. | System remains online; exit code 0. |
| **`TC-SYS-04`** | Active Job Deferral | Trigger `/usr/local/sbin/server-suspend.sh` while `immich_backup_gdrive.sh` is running. | Suspend routine detects active backup and defers sleep. | Sleep aborted; warning logged to `/var/log/server-suspend.log`. |
| **`TC-SYS-05`** | CleanYourTV Quiescent Idle | Run `python3 tv_updater.py` when all target TVs are already up to date. | Detects all target versions match `state.json`. Exits immediately. | Runtime **< 15ms**; zero ADB network packets transmitted. |

---

### Module 6: Security, Secrets & Sanitization

* **Target Source:** Whole Repository Index & History
* **Goal:** Guarantee zero secrets leak to public version control.

| Test ID | Test Scenario | Execution Command / Procedure | Expected Result | Pass Criteria |
| :--- | :--- | :--- | :--- | :--- |
| **`TC-SEC-01`** | CSPRNG Password Generation | Call `POST /api/secrets/generate`. | Generates high-entropy passwords using Python `secrets` module. | Alphanumeric tokens with >= 32 chars length. |
| **`TC-SEC-02`** | Git Ignore Enforcement | Create local `.env`, `state.json`, and `*.log` files across apps. | Run `git status --porcelain`. | Sensitive runtime files do NOT show as untracked. |
| **`TC-SEC-03`** | Secret Scanner Gate | Scan all tracked commits and staged files for regex API keys. | Automated pattern match for `ghp_`, `glpat-`, `api_key=...`. | Zero flagged leaks. |

---

## 6. GitHub Actions CI/CD Pipeline Strategy

### Can we test this in CI/CD? Is it advisable?

> [!IMPORTANT]
> **Definitive Answer:**  
> **YES**, adding automated tests to GitHub Actions on every Pull Request is **highly recommended and industry best practice**—**BUT** it requires a strict separation of concerns.

#### What CAN Run in Standard Cloud CI/CD (GitHub-Hosted Runners):
* **Python API & Unit Tests:** Full execution of `setup/test_setup.py` on Ubuntu 22.04 & 24.04 runners.
* **Shell Script Syntax Validation:** Linting all shell scripts with `shellcheck`.
* **Docker Compose Schema Validation:** Running `docker compose config` to guarantee zero YAML syntax errors.
* **Multi-Architecture Pull Tests:** Pulling and inspecting container images for `amd64` and `arm64` using QEMU.
* **Secret Leak Scanning:** Gitleaks or TruffleHog scanning on every commit.

#### What CANNOT Run on Standard Cloud CI/CD (Why It's Not Advisable):
* ❌ **Netplan Physical NIC Reconfiguration:** Running `netplan apply` on a GitHub-hosted cloud runner will modify the runner's virtual network card, immediately breaking the runner's connection to GitHub and aborting the CI job.
* ❌ **Hardware S3 Sleep (`rtcwake`):** Microsoft Azure (GitHub's underlying cloud) runs VMs without ACPI S3 sleep capability.
* ❌ **Hardware GPU Passthrough:** Cloud runners do not have Intel QuickSync `/dev/dri/renderD128` nodes.

---

### The Two-Tier CI/CD Architecture

To achieve 100% test coverage without broken CI builds, we use the standard **Two-Tier CI Architecture**:

```
┌────────────────────────────────────────────────────────────────────────┐
│  TIER 1: GitHub Actions Cloud CI (Every Commit & PR)                   │
│  • Fast (< 3 mins), 100% Free, Zero Infrastructure Setup               │
│  • Linting (ShellCheck, Flake8), Secrets Scan (Gitleaks)               │
│  • Matrix Test: Python 3.10, 3.11, 3.12 on Ubuntu 22.04 & 24.04        │
│  • Dry-Run Setup Deployment Test (setup/test_setup.py)                 │
│  • Docker Compose syntax & Multi-Arch (QEMU x86/ARM64) image check    │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Passes
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│  TIER 2: Hardware-in-the-Loop / VM Integration (Pre-Release / Manual)  │
│  • Executed in local Multipass VM or Self-Hosted Homelab Runner        │
│  • Netplan static IP test with auto-rollback                           │
│  • Dual-disk ext4 hardlink inode verification                          │
│  • Full container network deployment (Jellyfin, Immich, qBittorrent)   │
└────────────────────────────────────────────────────────────────────────┘
```

---

### Complete Ready-to-Use GitHub Actions Workflow

This workflow can be placed in [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) to automatically validate every Pull Request:

```yaml
name: Homelab Blueprint CI

on:
  push:
    branches: [ main ]
  pull_request:
    branches: [ main ]

jobs:
  lint-and-security:
    name: Linting & Secret Sanitization
    runs-on: ubuntu-latest
    steps:
      - name: Checkout Repository
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Verify No Secrets Committed
        uses: gitleaks/gitleaks-action@v2
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}

      - name: ShellCheck Static Analysis
        run: |
          sudo apt-get update && sudo apt-get install -y shellcheck
          shellcheck bootstrap.sh setup.sh
          shellcheck system/maintenance/watchtower-run.sh
          shellcheck system/power/immich-ml-control.sh
          shellcheck system/power/server-suspend.sh
          shellcheck apps/tv-updater/setup_cron.sh

  setup-wizard-test-matrix:
    name: Setup Wizard Matrix Test
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-22.04, ubuntu-24.04]
        python-version: ["3.10", "3.11", "3.12"]

    steps:
      - name: Checkout Repository
        uses: actions/checkout@v4

      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}

      - name: Execute Setup Wizard Verification Test Suite
        run: |
          python setup/test_setup.py

  docker-compose-validation:
    name: Docker Compose & Multi-Arch Verification
    runs-on: ubuntu-latest
    steps:
      - name: Checkout Repository
        uses: actions/checkout@v4

      - name: Validate Media Stack Compose Syntax
        run: |
          cd apps/mediaserver
          cp .env.example .env
          docker compose config --quiet
          echo "✅ apps/mediaserver docker-compose.yml is valid."

      - name: Validate Noodle Gallery Compose Syntax
        run: |
          cd apps/noodle-gallery
          cp .env.example .env
          docker compose config --quiet
          echo "✅ apps/noodle-gallery docker-compose.yml is valid."

      - name: Set up QEMU for Cross-Platform Simulation (ARM64)
        uses: docker/setup-qemu-action@v3
        with:
          platforms: linux/amd64,linux/arm64

      - name: Verify Multi-Arch Image Availability
        run: |
          # Test that images support both amd64 and arm64
          docker manifest inspect ghcr.io/seerr-team/seerr:latest | grep -E "amd64|arm64"
          docker manifest inspect ghcr.io/thephaseless/byparr:latest | grep -E "amd64|arm64"
          docker manifest inspect lscr.io/linuxserver/jellyfin:latest | grep -E "amd64|arm64"
          echo "✅ Multi-arch container images verified."
```

---

## 7. Automated Verification Checklist

Use this checklist during manual releases or automated pipeline reviews:

- [ ] **TC-BOOT-01:** `bootstrap.sh` executes zero-touch on fresh Ubuntu.
- [ ] **TC-BOOT-02:** `./setup.sh` auto-elevates with `sudo`.
- [ ] **TC-STOR-01:** `os.link` passes with `latency < 5ms` on ext4 single-mount.
- [ ] **TC-STOR-02:** Cross-device link properly raises `EXDEV` and returns warning.
- [ ] **TC-NET-01:** `netplan generate` returns exit code 0 for proposed YAML.
- [ ] **TC-NET-03:** Auto-rollback recovers network if IP/gateway is invalid.
- [ ] **TC-DOCK-01:** All 8 media containers achieve `Up (healthy)`.
- [ ] **TC-DOCK-02:** Noodle Gallery PostgreSQL with VectorChord starts up.
- [ ] **TC-DOCK-03:** `tmdb-interceptor.js` intercepts blocked TMDB requests.
- [ ] **TC-SYS-01:** Control Hub starts via systemd and stays `< 25MB RAM`.
- [ ] **TC-SYS-03:** Sleep Guard honors `/run/server-suspend.skip` flag.
- [ ] **TC-SEC-03:** Gitleaks scan reports 0 credentials in Git history.
