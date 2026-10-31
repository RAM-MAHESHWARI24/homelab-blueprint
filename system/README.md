# System Host Daemons, Power Management & Cron Services ⚙️🖥️

> Host-level orchestration, ACPI S3 power automation, background maintenance cron jobs, Linux kernel networking profiles, and systemd daemon units for the **Homelab Blueprint** server node.

---

## 📑 Table of Contents
1. [Overview & Architecture](#-overview--architecture)
2. [Component Directory Structure](#-component-directory-structure)
3. [Systemd Service Units (`system/systemd/`)](#-systemd-service-units-systemsystemd)
4. [Power Management & Sleep Guard (`system/power/`)](#-power-management--sleep-guard-systempower)
5. [Cron Job Automation (`system/cron.d/`)](#-cron-job-automation-systemcrond)
6. [Host Networking & File Sharing (`system/networking/`)](#-host-networking--file-sharing-systemnetworking)
7. [Maintenance Routines (`system/maintenance/`)](#-maintenance-routines-systemmaintenance)
8. [Cross-References & Documentation Links](#-cross-references--documentation-links)

---

## 🧭 Overview & Architecture

While application workloads (Jellyfin, qBittorrent, Immich, Radarr) run inside isolated Docker containers, **host-level responsibilities** require native Linux kernel access:
* **ACPI S3 Suspend & RTC Wakeup:** Lowers server power consumption to ~1.2W during idle nighttime windows and awakens automatically at 06:00 AM via hardware CMOS RTC alarms.
* **Control Hub Daemon (`control-hub.service`):** Native systemd service running the Flask telemetry sampler and configuration REST API outside container networking namespaces.
* **Maintenance & Cleanups:** Scheduled Docker container image pruning, Watchtower updates, and Smart TV fleet ADB provisioning.
* **Kernel & File Sharing Configuration:** Tailscale UDP optimization (`99-tailscale.conf`) and dual-share Samba permissions (`smb.conf.example`).

---

## 📂 Component Directory Structure

```
system/
├── systemd/
│   ├── control-hub.service               # Systemd daemon for Control Hub Flask runtime (unprivileged)
│   └── homelab-sudoers.example           # Least-privilege sudoers whitelist (/etc/sudoers.d/)
├── power/
│   ├── server-suspend.sh                 # Intelligent ACPI S3 sleep & self-healing wake script
│   ├── server-suspend.conf.example       # Threshold configuration (SMB, downloads, network limits)
│   └── immich-ml-control.sh              # Dynamically pauses Immich ML container before sleep
├── cron.d/
│   ├── server-suspend                    # Nightly sleep-check trigger (e.g., 00:00 midnight)
│   ├── immich-backup                     # Daily photo database & XMP sidecar backup trigger
│   ├── immich-ml                         # Schedule for ML face detection & CLIP indexing
│   ├── tv-updater                        # Weekly Android TV fleet ADB update routine
│   └── watchtower                        # Weekly container image update sweep
├── networking/
│   ├── 99-tailscale.conf                 # Sysctl kernel tuning (UDP buffers, IP forwarding)
│   └── smb.conf.example                  # Samba multi-mount definition (MediaDrive + RootFS)
└── maintenance/
    └── watchtower-run.sh                 # Docker container update execution wrapper
```

---

## 🔧 Systemd Service Units (`system/systemd/`)

### Control Hub Daemon (`control-hub.service`)

Runs the Control Hub web dashboard and telemetry daemon on port `7575`.

* **Service Definition:** `system/systemd/control-hub.service`
* **Security Model (Least Privilege):** Executes as unprivileged service user `User=homelab` with `SupplementaryGroups=docker` (instead of `root`), restricting daemon privileges.
* **Restart Policy:** `Restart=always` with 5-second backoff.
* **Resource Bounds:**
  ```ini
  CPUQuota=20%
  MemoryMax=100M
  ```
  Strict resource caps ensure telemetry polling never starves container workloads or runs away with host memory.

#### Installation & Security Setup:
```bash
# 1. Create unprivileged service user if not present
sudo useradd -r -s /usr/sbin/nologin -G docker homelab 2>/dev/null || true

# 2. Deploy least-privilege sudoers whitelist
sudo cp system/systemd/homelab-sudoers.example /etc/sudoers.d/homelab-blueprint
sudo chmod 0440 /etc/sudoers.d/homelab-blueprint

# 3. Link and enable systemd service
sudo cp system/systemd/control-hub.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now control-hub.service

# Inspect status and live logs
sudo systemctl status control-hub.service
sudo journalctl -u control-hub.service -f -n 50
```

---

## ⚡ Power Management & Sleep Guard (`system/power/`)

### 1. `server-suspend.sh`
The primary power orchestrator. Executes intelligent pre-sleep condition checks before suspending the machine into **ACPI S3** state via `rtcwake`:
1. **Skip Flag Check:** If `/run/server-suspend.skip` exists (toggled via Control Hub UI), sleep is cancelled for tonight.
2. **Override Check:** If `/run/server-suspend.override` exists, suspend is delayed by +1 or +2 hours.
3. **Active Downloads:** Probes qBittorrent Web API; delays sleep if downloads exceed minimum bandwidth threshold.
4. **Active LAN SMB Sessions:** Inspects `smbstatus` to ensure no clients are actively streaming or transferring files.
5. **Dynamic Wakeup Alarm:** Calculates seconds until next scheduled wake (default 06:00 AM) and executes:
   ```bash
   rtcwake -m mem -s "$SECONDS_UNTIL_WAKE"
   ```
6. **Post-Wake Self-Healing:** After resuming, restarts Docker daemon if needed, resets network adapters, and logs the full wake cycle.

### 2. `immich-ml-control.sh`
Pauses the resource-intensive machine learning container (`immich-machine-learning`) prior to sleep to prevent high CPU wakeups and memory lockups.

* **Documentation Deep Dive:** [Power Management & RTC Wake Guide](../docs/POWER_MANAGEMENT_RTCWAKE.md)
* **Architecture Decision:** [ADR-0003: ACPI S3 Sleep Guard](../docs/adr/0003-acpi-s3-sleep-guard-power-automation.md)

---

## ⏰ Cron Job Automation (`system/cron.d/`)

Cron configurations reside in standard `/etc/cron.d/` syntax:

| File | Schedule | Task Description |
| :--- | :--- | :--- |
| `server-suspend` | `0 0 * * *` (Midnight) | Evaluates sleep conditions and enters S3 sleep if idle |
| `immich-backup` | `0 3 * * *` (03:00 AM) | Dumps PostgreSQL DB and mirrors photos/XMPs |
| `immich-ml` | `0 4 * * *` (04:00 AM) | Runs batch face clustering & CLIP embeddings |
| `tv-updater` | `0 5 * * 0` (Sunday 05:00 AM) | Synchronizes smart TV apps via ADB over WiFi |
| `watchtower` | `0 4 * * 1` (Monday 04:00 AM) | Executes one-shot image update check via `watchtower-run.sh` |

#### Deployment:
```bash
sudo cp system/cron.d/* /etc/cron.d/
sudo chmod 644 /etc/cron.d/*
```

---

## 🌐 Host Networking & File Sharing (`system/networking/`)

### Kernel Network Tuning (`99-tailscale.conf`)
Enables UDP send/receive buffer optimizations and IPv4/IPv6 packet forwarding for Tailscale subnet routing:
```ini
net.ipv4.ip_forward = 1
net.ipv6.conf.all.forwarding = 1
net.core.rmem_max = 2500000
net.core.wmem_max = 2500000
```

Deploy with:
```bash
sudo cp system/networking/99-tailscale.conf /etc/sysctl.d/
sudo sysctl --system
```

### Samba Dual-Share Configuration (`smb.conf.example`)
Defines the two primary LAN network shares:
1. `[MediaDrive]`: Read/Write access to `/mnt/hdd/data` for daily file management and movie drop-offs.
2. `[RootFS]`: Secured administrative access to `/` for developer configuration from remote workstations.

* **Detailed Runbook:** [Networking: Tailscale & Samba](../docs/NETWORKING_TAILSCALE_SAMBA.md)

---

## 🛠️ Maintenance Routines (`system/maintenance/`)

### `watchtower-run.sh`
Performs a safe, non-destructive Docker container image update sweep:
* Pulls newest container tags for active services.
* Automatically prunes dangling images and unused build caches.
* Preserves database volumes and pinned container tags.

---

## 🔗 Cross-References & Documentation Links

* 📖 **[Master Documentation Portal](../docs/README.md)**
* ⚡ **[Power Management & RTC Wake Guide](../docs/POWER_MANAGEMENT_RTCWAKE.md)**
* 🌐 **[Networking & Samba Configuration](../docs/NETWORKING_TAILSCALE_SAMBA.md)**
* 🖥️ **[Control Hub Architecture](../apps/control-hub/README.md)**
* 🧪 **[Testing & Automated Verification](../testing/README.md)**

