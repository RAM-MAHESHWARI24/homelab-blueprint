# Docker File Permissions, PUID/PGID & Hardlink Quirks 🔑

## 1. Why "Permission Denied" Occurs
In Dockerized homelabs, containers run separate user environments from the Linux host:
* qBittorrent downloads files with its container UID.
* Sonarr / Radarr try to move or hardlink those files into `/data/media`.
* If user IDs or umasks mismatch, file creation fails with `Access to path /data/media/movies is denied`.

## 2. PUID and PGID Alignment
Linux permissions are based on numeric IDs, not username strings.
Identify your host user's numeric IDs:
```bash
id -u  # Typically 1000
id -g  # Typically 1000
```
Set these values consistently in `.env`:
```ini
PUID=1000
PGID=1000
```

## 3. UMASK 002 (Crucial for Multi-Container Collaboration)
Default Linux umask (`022`) creates files as `rw-r--r--` (group cannot write).
All Arr containers and qBittorrent should operate with `UMASK=002`:
* Files created with `rw-rw-r--` (Group Writable).
* Directories created with `rwxrwxr-x`.
Both downloaders and managers belonging to the same `PGID=1000` group can read, write, and create hardlink pointers without permission errors.

## 4. Fixing Existing Permission Collisions
To recursively align permissions across your media drive:
```bash
sudo chown -R 1000:1000 /mnt/hdd/data
sudo chmod -R 775 /mnt/hdd/data
```
