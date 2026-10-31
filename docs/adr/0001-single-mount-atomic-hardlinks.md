# ADR-0001: Single ext4 Mount for Atomic 0-I/O Hardlinks

## Status
**Accepted**

## Context
In self-hosted media setups running qBittorrent, Radarr, and Sonarr, completed downloads must be imported into final library directories (e.g. `/movies` or `/tv`) while remaining available in the download directory for continuous seeding.

If the torrent directory and media directory are mounted as separate Docker volumes (e.g. `-v /mnt/hdd/downloads:/downloads` and `-v /mnt/hdd/movies:/movies`), Linux treats them as different filesystem mount points inside the container namespaces. Consequently:
1. Docker and the Linux VFS cannot create an atomic directory link (raising `EXDEV: Invalid cross-device link`).
2. Radarr/Sonarr fall back to a full file copy, reading and writing tens of gigabytes across the storage bus.
3. Disk space consumption doubles (e.g., a 40 GB 4K movie consumes 80 GB on disk).
4. Mechanical hard drives (HDDs) suffer severe I/O head thrashing, spiking disk latency and degrading playback streams.

## Decision
We mandate a **single-mount `/data` storage hierarchy** across the entire homelab blueprint:
1. Host path `${HDD_DATA}` (default: `/mnt/hdd/data`) is mounted into every container at the identical internal root:
   ```yaml
   volumes:
     - ${HDD_DATA}:/data
   ```
2. The folder structure inside `/data` is strictly standardized:
   ```
   /data/
   ├── torrents/
   │   ├── movies/
   │   └── tv/
   └── media/
       ├── movies/
       └── tv/
   ```
3. Radarr and Sonarr are configured using root folders `/data/media/movies` and `/data/media/tv`. qBittorrent downloads to `/data/torrents/`.
4. Hardlinks are enforced across all services. When an import happens, `os.link` / `link(2)` creates a second directory entry referencing the exact same inode.

## Alternatives Considered
* **Separate Volume Mounts (`/downloads` and `/movies`):**
  * *Rejected:* Breaks Linux atomic hardlinks, doubles disk usage, and causes heavy disk I/O thrashing during media ingestion.
* **Symbolic Links (Symlinks):**
  * *Rejected:* Fragile across container path boundaries; if the source download is ever deleted or pruned, the symlink breaks and media players fail.
* **Btrfs / ZFS Copy-on-Write (reflink):**
  * *Rejected:* Imposes higher RAM overhead (ZFS ARC) and filesystem complexity on budget mini-PCs and repurposed hardware. Standard ext4 is universal, reliable, and supports instant hardlinks natively.

## Consequences
### Positive
* **Instant Ingestion:** Media files (even 80 GB remuxes) import in sub-millisecond time (< 5ms).
* **Zero Additional Disk Space:** Inodes share the exact same physical storage blocks; 0 bytes of extra disk consumed.
* **Continuous Seeding:** Seeding torrents remain completely undisturbed in `/data/torrents/` while Jellyfin streams from `/data/media/`.
* **Zero I/O Thrashing:** Eliminates mechanical disk read/write bottleneck during downloads.

### Negative / Trade-offs
* All media must reside on the same filesystem partition.
* Storage setup wizard and Control Hub must actively validate `os.link` capability prior to deployment (automated in `setup/config_core/storage_manager.py`).

## References
* [Storage Architecture & 0-I/O Hardlinks Guide](../STORAGE_AND_HARDLINKS.md)
* [Setup Wizard Storage Prober](../../setup/config_core/storage_manager.py)
* [Lifecycle Test TC-FLOW-02](../../testing/test_lifecycle_handoff.py)

