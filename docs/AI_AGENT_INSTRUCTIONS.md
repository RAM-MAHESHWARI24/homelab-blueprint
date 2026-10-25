# Master AI Agent Guidelines & Architectural Cheatsheet 🤖

> **Target Audience:** LLMs & AI Coding Agents (Claude, ChatGPT, Cursor, Copilot, Antigravity) helping operators configure or debug this homelab monorepo.  
> **Goal:** High density, zero wasted tokens. Consult these concise rules before proposing changes.

---

## 1. Top Architectural Invariants (Never Violate)

1. **Atomic Hardlinks Constraint ([`STORAGE_AND_HARDLINKS.md`](STORAGE_AND_HARDLINKS.md))**:
   - `qbittorrent`, `sonarr`, `radarr` MUST mount `/mnt/hdd/data:/data`.
   - Never split torrents and media into separate Docker mounts (e.g. `/torrents` and `/movies`). Separate mounts force file copying, burning 100% disk I/O and doubling disk space.
   - Filesystem must be ext4/xfs/btrfs; hardlinks do NOT work across NFS, SMB, or FAT32/exFAT.

2. **Safe Netplan Apply ([`NETPLAN_STATIC_IP_QUIRKS.md`](NETPLAN_STATIC_IP_QUIRKS.md))**:
   - Never propose `netplan apply` over an SSH session without pre-validation.
   - Always run `netplan generate` first, followed by `netplan try --timeout 45`.

3. **Low-Power CPU Transcode Protection ([`HASWELL_DIRECT_PLAY_GUIDE.md`](HASWELL_DIRECT_PLAY_GUIDE.md))**:
   - Haswell (i3-4005U) lacks 10-bit HEVC decoding blocks.
   - Do NOT attempt to enable 4K HEVC transcoding in Jellyfin for Haswell; enforce Direct Play clients (Jellyfin Media Player desktop app or ExoPlayer on TV).

4. **S3 RAM Suspend Safety Guards ([`POWER_MANAGEMENT_RTCWAKE.md`](POWER_MANAGEMENT_RTCWAKE.md))**:
   - Automated midnight sleep (00:00 -> 06:00, 1.2W).
   - Script checks `pgrep -f "rclone sync"` and `pgrep -f "immich_backup"`. Never remove these deferral guards.

5. **PUID/PGID Alignment ([`DOCKER_PERMISSIONS_PUID_PGID.md`](DOCKER_PERMISSIONS_PUID_PGID.md))**:
   - All containers run as `PUID=1000`, `PGID=1000` with `UMASK=002`.

6. **Control Hub Live Configuration ([`CONTROL_HUB_CONFIGURATION_CENTER.md`](CONTROL_HUB_CONFIGURATION_CENTER.md))**:
   - Control Hub exposes live configuration endpoints at `http://localhost:7575/api/config/*`.
   - Never recommend manual `.env` file editing when operators can test hardlinks and update settings directly via the GUI Settings drawer.

---

## 2. Directory Layout Reference

| Path | Purpose | Mount / Drive Type |
| :--- | :--- | :--- |
| `/` | OS root & overlay caches | Fast SSD |
| `apps/mediaserver/config` | SQLite databases for Jellyfin, Arr stack | Fast SSD (`./config`) |
| `apps/noodle-gallery/data/postgres` | PostgreSQL & VectorChord embeddings | Fast SSD |
| `/mnt/hdd/data` | Torrents & Media Library | Mechanical HDD (Single Mount) |
| `/mnt/hdd/Memories` | Photos & Videos storage | Mechanical HDD |

---

## 3. Fast Diagnostic Commands

* **Check Hardlink Support**:
  ```bash
  python3 -c "import os; os.link('/mnt/hdd/data/.src', '/mnt/hdd/data/.dst'); print('OK'); os.unlink('/mnt/hdd/data/.src'); os.unlink('/mnt/hdd/data/.dst')"
  ```
* **Check Port Occupancy**:
  ```bash
  sudo ss -tulpn | grep -E "(7575|8096|5055|8080|8989|7878|9696|2283)"
  ```
* **Verify Render Node**:
  ```bash
  ls -l /dev/dri/renderD128 && getent group render
  ```
* **Run Setup Web GUI**:
  ```bash
  python3 setup/server.py
  ```
* **Run Verification Test Suite**:
  ```bash
  python3 setup/test_setup.py
  ```
* **Query Control Hub Live Config via REST**:
  ```bash
  curl -s http://127.0.0.1:7575/api/config/current | jq .
  ```
