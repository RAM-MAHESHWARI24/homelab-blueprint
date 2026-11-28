# Installing v2 on a Server That Already Runs These Apps

This runbook moves a server that runs an older, hand-made setup onto the v2 installer. It was written for one specific server, but the steps apply to any host that already runs Immich and the Arr apps.

**The main risk is the photo database.** Immich migrates its database forward on startup and cannot go back. A new password or a different version will break or upgrade it. Follow the backup and pinning steps exactly.

## What the old server looks like

| Item | Old setup | After v2 |
| :--- | :--- | :--- |
| Dashboard | `serverff-control-hub.service`, user `server_ff`, sudo `NOPASSWD: ALL` | `control-hub.service`, user `homelab`, exact-argument sudoers |
| Photos | Compose project in `/opt/immich` | `apps/noodle-gallery`, env in `/etc/homelab/noodle-gallery.env` |
| TV updater | Cron as `server_ff` | `/etc/cron.d/tv-autoupdater` as `homelab` |
| Recyclarr, webhook listener | `server_ff` crontab | Unchanged unless you move them |
| Config | `.env` files in the checkout | `/etc/homelab/` |
| App data | Various | `/srv/homelab/appdata/` |

## 1. Record what is running

```bash
docker ps --format '{{.Names}}\t{{.Image}}'
docker inspect immich_server --format '{{.Config.Image}}'
docker inspect immich_machine_learning --format '{{.Config.Image}}'
grep -E '^(DB_PASSWORD|DB_USERNAME|DB_DATABASE_NAME|UPLOAD_LOCATION|DB_DATA_LOCATION)=' /opt/immich/.env
sudo crontab -l -u server_ff
systemctl cat serverff-control-hub.service
```

Write down the exact Immich server and ML image references, including the tag. If the tag is `release`, find the digest:

```bash
docker inspect immich_server --format '{{index .RepoDigests 0}}'
```

## 2. Back up

Stop nothing yet. Dump the photo database while it runs:

```bash
sudo mkdir -p /root/pre-v2
docker exec -t immich_postgres pg_dumpall --clean --if-exists -U postgres | gzip > /root/pre-v2/immich-db.sql.gz
```

Then copy the app configs and the old Immich folder:

```bash
sudo tar czf /root/pre-v2/arr-appdata.tgz <path-to-current-arr-configs>
sudo tar czf /root/pre-v2/opt-immich.tgz --exclude='*/postgres/*' /opt/immich
sudo cp /etc/sudoers.d/* /root/pre-v2/
```

Check that the dump is not empty: `zcat /root/pre-v2/immich-db.sql.gz | head`.

## 3. Write the install profile

Create `/root/pre-v2/profile.json`. Reuse the existing database password and pin the images you recorded in step 1:

```json
{
  "host_user": "<your login user>",
  "puid": 1000,
  "pgid": 1000,
  "hdd_data": "/mnt/hdd/data",
  "hdd_memories": "/mnt/hdd/Memories",
  "enable_static_ip": false,
  "enabled_services": ["media", "photos", "control_hub"],

  "postgres_password": "<DB_PASSWORD from /opt/immich/.env>",
  "postgres_user": "<DB_USERNAME>",
  "postgres_db": "<DB_DATABASE_NAME>",
  "photo_upload_dir": "<UPLOAD_LOCATION>",
  "photo_db_dir": "<DB_DATA_LOCATION>",
  "photo_external_mount_path": "<container path of the external library, e.g. /mnt/hdd/Memories>",
  "photo_external_mount_mode": "rw",
  "photos_server_image": "ghcr.io/immich-app/immich-server:<exact tag or @sha256 digest>",
  "photos_ml_image": "ghcr.io/immich-app/immich-machine-learning:<same version>"
}
```

- `photo_db_dir` points at the existing Postgres data, so the database is reused in place.
- A default database password (`postgres`, `changeme`, `password` and similar) is never kept: the installer generates a new one and the photo server then fails to log in to the existing database. After the install, give the database the new password (`DB_PASSWORD` in `/etc/homelab/noodle-gallery.env`): `docker exec -it immich_postgres psql -U postgres -c "ALTER USER postgres WITH PASSWORD '<new password>'"`, then `docker restart immich_server`.
- External library assets store absolute paths, so `photo_external_mount_path` must be the path the old compose file mounted the library at inside the container (the right-hand side of its volume line). The blueprint default is `/mnt/media`; a different path makes every external asset go offline. Use `rw` if the old mount was read-write, so the server can keep writing XMP sidecars. Check with `docker inspect immich_server --format '{{json .Mounts}}'` before you stop it.
- The two image keys keep the version the database was migrated to. Without them, the blueprint's own pinned images start, and those are Open-Noodle Gallery, a fork, at a different version.
- Media apps start fresh under `/srv/homelab/appdata/mediaserver` by default. To keep the existing Arr configs, set `"config_dir"` to the folder that holds them and `"qbittorrent_pass"` to qBittorrent's current WebUI password. An existing `qBittorrent.conf` is never overwritten, so a different password makes the wiring step fail.

## 4. Stop the old services

```bash
cd /opt/immich && docker compose down
sudo systemctl disable --now serverff-control-hub.service
sudo crontab -l -u server_ff > /root/pre-v2/server_ff.crontab
```

Remove the TV updater line from the `server_ff` crontab. Keep the Recyclarr and webhook lines if you still want them.

Stop any old Arr containers that publish the same ports (8080, 9696, 7878, 8989, 6767, 8096, 5055).

## 5. Install

```bash
sudo git clone https://github.com/RAM-MAHESHWARI24/homelab-blueprint.git /opt/homelab-blueprint
cd /opt/homelab-blueprint
./setup.sh --doctor
sudo ./setup.sh --headless --config /root/pre-v2/profile.json
```

The output ends with the credentials. You sign in to the Control Hub with the master password (`media_admin_pass`, or `qbittorrent_pass` when that is not set); set `control_hub_password` in the profile to use a different one.

## 6. Check

- Immich at `http://<ip>:2283` shows your existing library and users.
- `docker inspect immich_server --format '{{.Config.Image}}'` matches the image from step 1.
- The Control Hub at `http://<ip>:7575` accepts the master password. Change it under Account, or with `sudo ./setup.sh password`.
- `sudo -l -U server_ff` no longer shows a blanket rule once you remove the old sudoers file.

When everything works, remove the old pieces:

```bash
sudo rm /etc/sudoers.d/<old blanket rule file>
sudo rm /etc/systemd/system/serverff-control-hub.service && sudo systemctl daemon-reload
```

Keep `/opt/immich` and `/root/pre-v2` for a few weeks.

## Rollback

1. `sudo /opt/homelab-blueprint/teardown.sh --yes`. This keeps media, photos and databases.
2. If the photo database was changed, restore it:

   ```bash
   cd /opt/immich && docker compose up -d database
   zcat /root/pre-v2/immich-db.sql.gz | docker exec -i immich_postgres psql -U postgres
   ```

3. `cd /opt/immich && docker compose up -d`.
4. Restore the old sudoers file and `sudo systemctl enable --now serverff-control-hub.service`.
5. `sudo crontab -u server_ff /root/pre-v2/server_ff.crontab`.

## Upgrading or syncing an existing v2 server

On an already-installed v2 server under `/opt/homelab-blueprint`:

1. **Update application code:** Use Control Hub's **Update Centre -> Self-Update Blueprint**, or pull on the host directly:

   ```bash
   sudo git -C /opt/homelab-blueprint pull --ff-only origin develop   # or checkout a release tag such as v2.2.0
   sudo systemctl restart control-hub.service
   ```

2. **Sync newly added host helpers, cron jobs, timers, and `.env` keys:** `git pull` updates files inside `/opt/homelab-blueprint`, while host-installed files (`/usr/local/sbin/homelab-*` helpers like `homelab-update`, `homelab-storage-ops`, `homelab-config-apply`; systemd units/timers like `homelab-storage-sizes.timer`; sudoers rules; and `/etc/cron.d/*` jobs like `mediaserver-autoimport`) are rendered by Setup. After checking diffs cleanly, check `.env` schema updates and re-apply headless setup using the saved profile:

   ```bash
   cd /opt/homelab-blueprint
   sudo ./setup.sh --migrate --check
   sudo ./setup.sh --migrate
   sudo ./setup.sh --headless --config /etc/homelab/config.json --dry-run
   # Once satisfied with the dry-run preview:
   sudo ./setup.sh --headless --config /etc/homelab/config.json
   ```

3. **Remove legacy pre-v2.1 untracked directories (if upgrading from v2.0):** If `/opt/homelab-blueprint/apps/tv-updater` still exists alongside `apps/tv-autoupdater` as an untracked directory, remove or archive it once `tv-autoupdater` is confirmed active so `testing/test_module_contract.py` stays clean.
