# System Host Daemons, Power Management & Cron Services ⚙️🖥️

> Host-level orchestration, ACPI S3 power automation, background maintenance cron jobs, Linux kernel networking profiles, and systemd daemon units for the **Homelab Blueprint** server node.

---

## 📑 Table of Contents
1. [Overview & Architecture](#-overview--architecture)
2. [Component Directory Structure](#-component-directory-structure)
3. [Systemd Service Units (`system/systemd/`)](#-systemd-service-units-systemsystemd)
4. [Module Host Files (moved)](#-module-host-files-moved)
5. [Host Networking & File Sharing (`system/networking/`)](#-host-networking--file-sharing-systemnetworking)
6. [Cross-References & Documentation Links](#-cross-references--documentation-links)

---

## 🧭 Overview & Architecture

While application workloads (Jellyfin, qBittorrent, Immich, Radarr) run inside isolated Docker containers, **host-level responsibilities** require native Linux kernel access:
* **ACPI S3 Suspend & RTC Wakeup:** Lowers server power consumption to ~1.2W during idle nighttime windows and awakens automatically at 06:00 AM via hardware CMOS RTC alarms.
* **Control Hub Daemon (`control-hub.service`):** Native systemd service running the Flask telemetry sampler and configuration REST API outside container networking namespaces.
* **Maintenance:** Smart TV fleet ADB provisioning. Container images are pinned and updated through Dependabot pull requests (no Watchtower).
* **Kernel & File Sharing Configuration:** Tailscale UDP optimization (`99-tailscale.conf`) and LAN shares for the media and photo folders (`homelab-shares.conf.example`).

---

## 📂 Component Directory Structure

```
system/
├── systemd/
│   ├── control-hub.service               # Systemd daemon for Control Hub Flask runtime (unprivileged)
│   └── homelab-sudoers.example           # Least-privilege sudoers whitelist (/etc/sudoers.d/)
├── networking/
│   ├── 99-tailscale.conf                 # Sysctl kernel tuning (UDP buffers, IP forwarding)
│   └── homelab-shares.conf.example       # Samba share definitions (Media + Photos), included from smb.conf
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

## 📦 Module Host Files (moved)

Host scripts and cron templates now live with the module they belong to, so each module's published repo carries them. The installer renders the cron templates (`{{INSTALL_DIR}}`, `{{STATE_DIR}}` and similar placeholders) and installs them to `/etc/cron.d/`.

| File | Module folder | Installed as | Schedule |
| :--- | :--- | :--- | :--- |
| `server-suspend.sh` | `apps/control-hub/host/` | `/usr/local/sbin/server-suspend.sh` | Run by the cron below |
| `server-suspend.conf.example` | `apps/control-hub/host/` | `/etc/server-suspend.conf` | Sleep and wake times |
| `cron/server-suspend` | `apps/control-hub/host/` | `/etc/cron.d/server-suspend` | 00:00, checks whether the server can sleep |
| `cron/immich-ml` | `apps/immich-face-xmp-exporter/host/` | `/etc/cron.d/immich-ml` | Starts the photo ML container at 06:00, stops it at 10:00 |
| `cron/immich-backup` | `apps/immich-face-xmp-exporter/host/` | `/etc/cron.d/immich-backup` | 22:00, database dump, XMP export and rclone mirror |
| `cron/tv-autoupdater` | `apps/tv-autoupdater/host/` | `/etc/cron.d/tv-autoupdater` | Every 15 minutes from 06:00 to 23:45 |
| `post-wake-arr.sh` | `apps/mediaserver/host/` | `/etc/server-suspend.d/50-mediaserver.sh` | After every resume |

The suspend script's checks and post-wake hooks are described in the [Power Management & RTC Wake Guide](../docs/POWER_MANAGEMENT_RTCWAKE.md) and [ADR-0003](../docs/adr/0003-acpi-s3-sleep-guard-power-automation.md).

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

### Samba Shares (`homelab-shares.conf.example`)
Share definitions only; the distribution's `[global]` section is left alone. The installer renders the
placeholders, writes `/etc/samba/homelab-shares.conf` and appends `include = /etc/samba/homelab-shares.conf`
to `smb.conf`:
1. `[Media]`: read/write access to the media root (`DATA_DIR`) for the host user.
2. `[Photos]`: read/write access to the photo library (`MEMORIES_DIR`) with macOS `vfs_fruit` extras.

* **Detailed Runbook:** [Networking: Tailscale & Samba](../docs/NETWORKING_TAILSCALE_SAMBA.md)

---

## 🔗 Cross-References & Documentation Links

* 📖 **[Master Documentation Portal](../docs/README.md)**
* ⚡ **[Power Management & RTC Wake Guide](../docs/POWER_MANAGEMENT_RTCWAKE.md)**
* 🌐 **[Networking & Samba Configuration](../docs/NETWORKING_TAILSCALE_SAMBA.md)**
* 🖥️ **[Control Hub Architecture](../apps/control-hub/README.md)**
* 🧪 **[Testing & Automated Verification](../testing/README.md)**

