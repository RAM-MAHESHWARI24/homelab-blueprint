# Homelab Blueprint - End-to-End Pipeline Verification & Multipass VM Testing Report

> [!NOTE]
> **Host Isolation Guarantee**: All provisioning, Docker containers, loopback ext4 volume mounts, and test assertions were executed strictly inside the ephemeral Hyper-V Virtual Machine (`homelab-test`) on the Windows host. Zero commands, containers, or test modifications were touched on the physical server (`192.168.1.31`).

---

## 1. Executive Summary & Environment Evolution

| Verification Target | Engine / Environment | Gates Executed | Result | Duration |
| :--- | :--- | :---: | :---: | :---: |
| **Initial Pre-Verification** | WSL2 Ubuntu 24.04 micro-VM *(Hyper-V disabled)* | 8 / 8 Gates | **PASS (100%)** | 86.70s |
| **Canonical Multipass Hyper-V VM** | Standalone VM `homelab-test` (`172.21.188.196`) | 8 / 8 Gates | **PASS (100%)** | 18.52s (Cached) |
| **Complete System Lifecycle Suite** | Standalone VM `homelab-test` (`172.21.188.196`) | 7 / 7 Gates | **PASS (100%)** | 11.57s |
| **Docker Image Caching** | Local VM VHDX (`homelab-test`) | 12 Images Cached | **100% Offline** | 0s Pull Latency |
| **Atomic Inode Hardlink Invariant** | Dedicated Loopback ext4 (`/data`) | `st_ino=1005` Identity | **PASS** | 0 Extra I/O |

### Environment Clarification & Timeline
1. **Initial Hyper-V Absence**: When the user first attempted `multipass launch`, Windows returned `launch failed: The Hyper-V service does not exist` because the Windows Hyper-V Virtual Machine Management service (`vmms`) was not installed. Prior to Hyper-V activation, initial verification ran inside Windows Subsystem for Linux (WSL2).
2. **Hyper-V Activation**: The user enabled `Microsoft-Hyper-V -All` via PowerShell and rebooted Windows.
3. **Dedicated Multipass VM Provisioning**: Canonical Multipass successfully launched `homelab-test`:
   - **OS**: Ubuntu 24.04.5 LTS
   - **IP Address**: `172.21.188.196`
   - **Hardware Specs**: 4 vCPUs, 6 GB RAM, 32.7 GB Disk
4. **100% In-Guest Execution**: All subsequent pre-flight checks, setup wizard operations, container deployments, and pipeline tests were performed directly inside the `homelab-test` VM.

---

## 2. Issues Discovered in Pristine VM & Engineering Fixes

| Issue Encountered | Root Cause | Engineering Fix Applied |
| :--- | :--- | :--- |
| `launch failed: The Hyper-V service does not exist` | Hyper-V optional feature was disabled on the Windows 11 host. | Enabled `Microsoft-Hyper-V -All` and verified `vmms` service is running. |
| `[Errno 13] Permission denied: '/opt/homelab-blueprint/.hl_src_probe_...'` | `setup.sh --doctor` was placed before root elevation check in `setup.sh`. When non-root user `ubuntu` executed it, test file probes failed. | Moved `if [ "$EUID" -ne 0 ]; then exec sudo bash "$0" "$@"` to line 1 of `setup.sh`, ensuring root privilege escalation before any flag processing. Updated `README.md` to instruct `sudo ./setup.sh --doctor`. |
| Missing Docker & Python tooling on clean Ubuntu 24.04 | Vanilla cloud images do not pre-install container engines or build utilities. | Installed `docker.io` (`v29.1.3`), `docker-compose-v2` (`v2.40.3`), `jq`, `python3-venv`, and `ffmpeg` (`v6.1.1`) inside `homelab-test`. |
| `HTTPError: 400 Unable to connect to qBittorrent` | qBittorrent v4.6.1+ / v5.x rejects `0.0.0.0/0` subnet whitelist and generates random temporary session passwords if PBKDF2 hash is missing. | Pre-seeded `WebUI\Password_PBKDF2` hash for `adminadmin`, configured RFC 1918 CIDRs (`10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 127.0.0.1/32`), and updated Radarr/Sonarr download client configurations with authentication credentials. |

---

## 3. Full Media Stack Pipeline Architecture & Flow

The live 8-stage pipeline tests the full real-world interaction across all media services:

```mermaid
sequenceDiagram
    autonumber
    actor User as User / Test Harness
    participant Seerr as Seerr (:5055)
    participant Radarr as Radarr (:7878)
    participant Prowlarr as Prowlarr (:9696)
    participant Indexer as Mock Torznab (:9999)
    participant qBit as qBittorrent (:8080)
    participant Disk as Linux ext4 (/data)
    participant Jellyfin as Jellyfin (:8096)

    User->>Seerr: Request Movie (Big Buck Bunny, TMDB 10378)
    Seerr->>Radarr: Push Ingestion Payload (POST /api/v3/movie)
    Radarr->>Prowlarr: Trigger Search Query (MoviesSearch)
    Prowlarr->>Indexer: Torznab XML Search (t=movie, imdbid=10378)
    Indexer-->>Prowlarr: Return BEP 19 Torrent XML with Web Seed
    Prowlarr-->>Radarr: ApplicationIndexerSync Release Candidates
    Radarr->>qBit: Dispatch Torrent Grab (POST /api/v3/release)
    qBit->>Indexer: BEP 19 HTTP Range Download (/media/...)
    Indexer-->>qBit: Stream 120s H.264/AAC MKV (2004475 bytes)
    qBit->>Disk: Write to /data/torrents/movies/ (Progress: 100%)
    Radarr->>Disk: Completed Download Handling (CDH) Import
    Note over Radarr,Disk: Atomic Hardlink: ln /data/torrents/... /data/media/...
    Radarr->>Disk: Assert st_ino(src) == st_ino(dst) & st_nlink >= 2
    Radarr->>Jellyfin: Invalidate Cache & Trigger Library Discovery
    Jellyfin->>Disk: Scan /data/media/movies & Guard Stream
```

---

## 4. In-Guest Verification Evidence (`homelab-test`)

### Stage 1: Storage Topology & Environment
- **Loopback Volume**: Dedicated 4GB ext4 volume mounted at `/data` (`/drive_media.img`).
- **Permissions**: Chowned to `1000:1000` (`abc:abc`) with `0775` mode across `/data/torrents` and `/data/media`.
- **qBittorrent Configuration**: PBKDF2 hash seeded for `adminadmin` and `WebUI\AuthSubnetWhitelist` configured with `10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 127.0.0.1/32`.
- **Seerr TMDB Interceptor**: Injected `tmdb-interceptor.js` into `/app/config/` for DNS override.

### Stage 2: Mock Torznab Indexer & BEP 19 Web Seed
- **Endpoint**: Local Python standard library server listening on port `9999`.
- **Protocol**: Validated `t=caps`, `t=movie`, and `/download/*.torrent`.
- **Web Seeding**: Serves genuine 120s H.264/AAC Matroska video with full HTTP 206 Partial Content range streaming.

### Stage 3: Container Orchestration & Health
All 8 containers started cleanly using pre-cached images:
- `qbittorrent` (:8080, :6881) $\rightarrow$ Online (`HTTP 200`)
- `radarr` (:7878) $\rightarrow$ Online (`HTTP 401` API auth challenged)
- `sonarr` (:8989) $\rightarrow$ Online (`HTTP 401` API auth challenged)
- `prowlarr` (:9696) $\rightarrow$ Online (`HTTP 401` API auth challenged)
- `seerr` (:5055) $\rightarrow$ Online (`HTTP 200`, Next.js ready)
- `jellyfin` (:8096) $\rightarrow$ Online (`HTTP 200`, Server ID `38135e062bdc`)
- `bazarr` (:6767) $\rightarrow$ Online
- `byparr` (:8191) $\rightarrow$ Online

### Stage 4 & 5: API Key Extraction & Inter-Service Wiring
- Automated zero-touch extraction of API tokens from XML config files (`/config/config.xml`).
- Configured Radarr & Sonarr Root Folders: `/data/media/movies` and `/data/media/tv`.
- Configured qBittorrent download clients in Radarr and Sonarr with category separation (`movies` / `tv`) and credentials (`admin:adminadmin`).
- Added Mock Torznab Indexer to Radarr and Prowlarr (`appProfileId=1`, `priority=25`).
- Dispatched `ApplicationIndexerSync` command in Prowlarr (`status 201`).

### Stage 6: Ingestion, Download & Atomic Hardlink Verification
- Target Movie added: **Big Buck Bunny (2008)**, TMDB ID 10378.
- Radarr executed `MoviesSearch` and evaluated indexer release candidates.
- Release grabbed and queued into qBittorrent:
  ```
  qBit Torrent: 'Big.Buck.Bunny.2008.1080p.WEBDL.AAC2.0.H.264-MOCK.mkv' State: stalledUP Progress: 100.0%
  ```
- Radarr Completed Download Handling automatically imported the movie to:
  `/data/media/movies/Big Buck Bunny (2008)/Big.Buck.Bunny.2008.1080p.WEBDL.AAC2.0.H.264-MOCK.mkv`
- **Zero-I/O Hardlink Verification**:
  ```
  Torrent File:  Big.Buck.Bunny.2008.1080p.WEBDL.AAC2.0.H.264-MOCK.mkv (inode=1005)
  Library File:  Big.Buck.Bunny.2008.1080p.WEBDL.AAC2.0.H.264-MOCK.mkv (inode=1005)
  Link Count:    2
  VERDICT:       PASS - Inodes match identically. Atomic hardlink completed with 0 extra disk I/O!
  ```

### Stage 7 & 8: Jellyfin & Seerr Health
- **Jellyfin**: Verified public status (`v12.4.0`), `/Library/Refresh` confirmed active token protection (`401`).
- **Seerr**: Verified `/api/v1/status` (`v3.5.1`, commit `564bfb08`), TMDB Interceptor operational.

---

## 5. Docker Image Cache Status (100% Offline)

All necessary container images for both the Mediaserver stack and the Immich photos stack are persistently cached within the `homelab-test` VM disk:

| Container Image | Tag | Content Size | Cached Disk Size | Pull Time on Run |
| :--- | :--- | :---: | :---: | :---: |
| `ghcr.io/thephaseless/byparr` | `latest` | 930 MB | 3.47 GB | **0.00s (Cached)** |
| `ghcr.io/open-noodle/gallery-server` | `release` | 614 MB | 2.49 GB | **0.00s (Cached)** |
| `ghcr.io/seerr-team/seerr` | `latest` | 254 MB | 1.34 GB | **0.00s (Cached)** |
| `lscr.io/linuxserver/jellyfin` | `latest` | 351 MB | 1.28 GB | **0.00s (Cached)** |
| `ghcr.io/open-noodle/gallery-ml` | `release` | 268 MB | 1.10 GB | **0.00s (Cached)** |
| `ghcr.io/immich-app/postgres` | `14-vectorchord...` | 205 MB | 989 MB | **0.00s (Cached)** |
| `lscr.io/linuxserver/bazarr` | `latest` | 160 MB | 641 MB | **0.00s (Cached)** |
| `lscr.io/linuxserver/qbittorrent` | `latest` | 104 MB | 343 MB | **0.00s (Cached)** |
| `lscr.io/linuxserver/radarr` | `latest` | 94.7 MB | 313 MB | **0.00s (Cached)** |
| `lscr.io/linuxserver/sonarr` | `latest` | 90.8 MB | 302 MB | **0.00s (Cached)** |
| `lscr.io/linuxserver/prowlarr` | `latest` | 84.6 MB | 277 MB | **0.00s (Cached)** |
| `valkey/valkey` | `9` | 44.3 MB | 167 MB | **0.00s (Cached)** |

Repeat test runs consume **zero internet bandwidth** and execute in seconds.

---

## 6. Full Lifecycle Suite Test Summary (`test_vm_lifecycle.py`)

Executed directly inside `homelab-test` (`172.21.188.196`):

```
=================================================================
       VM END-TO-END TEST SUITE SUMMARY: PASS
=================================================================
  Total Gates Executed: 7
  Passed:               7
  Failed:               0
  Total Duration:       11.57s
=================================================================
```

| Phase / Gate | Measured Duration | Result | Assertion Verified |
| :--- | :---: | :---: | :--- |
| **Phase A: Storage_Loopback_Mount** | 0.004s | **PASS** | ext4 loopback filesystem mounted at `/data` |
| **Phase B: Headless_Deployment** | 10.642s | **PASS** | Unattended deployment completed with zero errors |
| **Phase C: Mock_Torznab_Startup** | 0.570s | **PASS** | Python Torznab mock listening on port `9999` |
| **Phase C: Mock_Torznab_Protocol** | 0.040s | **PASS** | Torznab XML capabilities, search feed, and .torrent verified |
| **Phase D: Media_Download** | 0.020s | **PASS** | Downloaded 2,004,475 bytes to `/data/torrents` |
| **Phase D: Inode_Identity_Invariant** | 0.020s | **PASS** | `st_ino=1313` identical, `st_nlink=2` (0 I/O copy verified) |
| **Phase E: Backup_Archive_Integrity** | 0.295s | **PASS** | `gzip -t` verified cleanly (1,760,750 bytes archive) |

---

## 7. Verification Artifacts & Test Logs

- **JSON Summary**: [`testing/vm/reports/vm_test_results.json`](file:///z:/opt/homelab-blueprint/testing/vm/reports/vm_test_results.json)
- **JUnit XML**: [`testing/vm/reports/vm_test_results.xml`](file:///z:/opt/homelab-blueprint/testing/vm/reports/vm_test_results.xml)
- **Integration Test Script**: [`testing/vm/test_full_container_pipeline.py`](file:///z:/opt/homelab-blueprint/testing/vm/test_full_container_pipeline.py)
- **VM Lifecycle Script**: [`testing/vm/test_vm_lifecycle.py`](file:///z:/opt/homelab-blueprint/testing/vm/test_vm_lifecycle.py)
