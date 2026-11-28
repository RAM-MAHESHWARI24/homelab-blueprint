# Changelog

All notable changes to this project are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **Release profile pack (`apps/mediaserver/profiles/`)** replaces Recyclarr. `wire_arr.py profiles apply|check|migrate` creates two profiles in Radarr and Sonarr: `1080p Compact` (best quality per GB) and `Dual Audio First` (for a second audio language). Both put every acceptable 720p/1080p quality in one `HD` group, so untagged "1080p" uploads no longer outrank BluRay and WEB releases, and let custom-format scores decide: 1080p, the second language, HEVC, a compact size band and the source. Junk and theatre recordings, banned uploaders, commentary editions, AV1 and Dolby Vision without HDR10 are rejected. The pack also sets size limits, Radarr's soft-subtitle whitelist (`ESub`), the recycle bin, a delay-profile bypass for near-perfect releases, Prowlarr Full Sync and minimum seeders 4, and qBittorrent's "seed while it helps" limits, queue limits, evening upload limit, public tracker list and excluded file names. Only objects with the pack's name prefixes are changed. TRaSH Guides formats are vendored with their upstream commit and licence, and a weekly workflow (`trash-sync.yml`) opens a pull request when they change. A corpus test checks every regex against real release titles. See [ADR-0004](docs/adr/0004-repo-owned-release-profiles.md) and the [release profiles guide](docs/MEDIA_RELEASE_PROFILES.md).
- **Setup Wizard "Release preferences" step:** second audio language, default profile, what the players decode, seeding, stuck-download handling, and a switch to leave profiles to another tool. Answers go to `config.json` and `mediaserver.env` (`MEDIA_*`); `/api/deploy` rejects invalid ones with HTTP 400. Express mode asks for the language only.
- Guide: [playing over SMB with Nova Video Player](docs/SMB_PLAYBACK_WITH_NOVA.md) (NFO metadata owned by Radarr/Sonarr, audio and subtitle language, codecs, resume files).

### Changed
- `wire_arr.py wire` moves Prowlarr's existing app links to Full Sync, so indexer priorities reach Radarr and Sonarr, and wires the download clients to the apps' default categories `radarr` and `tv-sonarr` (an existing `movies`/`tv` pair is left alone).
- Seerr is registered after the profiles are applied, with the chosen default profile.
- The schema migrator adds `MEDIA_PROFILES=off` to an existing install's `mediaserver.env`: an upgraded server keeps its current profiles until its owner runs `profiles migrate`.

### Removed
- The Recyclarr example (`apps/mediaserver/recyclarr/`) and its README section. It ranked `HDTV-1080p` highest and its daily sync reverted fixes; the guide keeps a short "using Recyclarr instead" note.
- The `Ozlem` restriction in `wire_arr.py`: `/api/v3/restriction` no longer exists in Radarr 7 or Sonarr 4, so it did nothing. The pack's `Junk · Banned uploaders` format replaces it.
- `scripts/setup_sonarr_season_preference.py` (used `requests` and title-regex season formats); TRaSH's Season Pack format in the pack replaces it.
- `RECYCLARR_LOG_FILE` from the Control Hub env template (the Schedules card still shows Recyclarr when it is installed).

## [2.2.0] - 2026-11-28

### Added
- **Control Hub Operations Console redesign (Pivot A–C, PRs `#56`–`#65`):** Restructured the dashboard into a 5-view hash-routed workspace (`Overview`, `Apps`, `Backups`, `TVs`, `System`) using the Hallmark `Console` design system (`console: graphite` dark, `console: paper` light), self-hosted offline `.woff2` fonts (`Host Grotesk` & `Atkinson Hyperlegible Mono`), collapsible icon-rail navigation, hairline-divided benches/ledgers, and zero fake or fallback telemetry.
- **Update Centre & Auto-Patch Policy (Phase 2C, PRs `#66`–`#67`):** Compares running Compose tags and Blueprint release versions against GitHub releases, surfaces major-upgrade warnings, and runs one-click container updates or blueprint self-updates with pre-update config backup and automatic health rollback via `homelab-update`.
- **Guided Add-a-TV Wizard & Fleet CRUD (Phase 2D, PR `#68`):** Phone-friendly ADB onboarding wizard with LAN scan, live pairing prompt detection, model/Android probe, nickname/IP edits, connection tests, pause toggle, and removal stored in `tv_profiles.json`.
- **Container Lifecycle & Inline Log Drawer (Phase 2E, PR `#69`):** Live Docker healthcheck badges, version tags, restart counts, streaming-aware confirmations before stop/restart, and a searchable inline container log drawer.
- **Media & Photo Management Hubs (Phase 3A–3B, PRs `#70`–`#72`):** Per-torrent pause/resume/delete/priority and evening speed schedules; Prowlarr indexer diagnostics and live tests; Seerr request approve/decline; Radarr/Sonarr 7-day calendar and Jellyfin library scans; Immich per-user storage, live ML schedule editor, BullMQ queue visibility, Face-to-XMP status, and folder health checks.
- **Storage Analytics, Safe Config Apply, Network & Schedules (Phase 3C–3F, PRs `#73`, `#74`, `#77`, `#78`):** Per-folder storage breakdown and 30-day fill forecast (`homelab-storage-sizes.timer`), one-click safe cleanups and SMART disk health (`homelab-storage-ops`), audited diff-preview/undo Settings editor (`homelab-config-apply`) + redacted support bundle and manifest viewer, NIC duplex/Tailscale/port-map diagnostics with 120 s Netplan IP confirmation, and a unified editable schedule manager with sleep-window clash detection.
- **Access Control, Remote HTTPS, PWA, History, Customization & Integrations (Phase 3G & Phase 4A–4F, PRs `#79`–`#82`):** Per-device server-side session management, optional RFC 6238 owner TOTP with recovery codes, read-only LAN Family View, Tailscale Serve HTTPS integration + onboarding guide (`docs/TAILSCALE_REMOTE_HTTPS.md`), installable offline PWA + Web Notifications, 24h/7d/30d telemetry history charts + Sleep Guard kWh/CO₂ savings report, WCAG AAA High-Contrast theme, English/Hindi localization, per-device card layout customizer + Wall Kiosk mode, Home Assistant REST sensor export, NUT UPS monitoring, scoped bearer API tokens, unified Troubleshoot runner, and contextual How-To guides.
- **Title-Verified Media Auto-Import & Queue Hardening (`apps/mediaserver`, PRs `#75`–`#76`):** Added `scripts/auto_import.py` and `wire_arr.py` hardening to resolve Radarr/Sonarr ID-matched manual imports when normalized titles verify safely, configure qBittorrent v5 excluded payload extensions, deprioritize unmoderated trackers, and default Seerr `NODE_OPTIONS` to `--dns-result-order=ipv4first`.
- **Change remote** on the backup card: pick another rclone remote (and folder), test it, and switch the photo and media settings backups to it, without editing files on the server. A root helper (`/usr/local/sbin/homelab-backup-remote`, one sudoers line) does the checking and the edits.
- Monthly restore test of the photo backup (first Sunday, 11:00): the newest database dump is downloaded from the remote, restored into a throwaway database from the live image, and the photos counted against the dump. The result is on the backup card, with **Run restore test now**, and a failure sends a critical alert.
- Nightly off-site backup of the media apps' settings (21:30, with the photo backup's remote): Sonarr, Radarr, Prowlarr, Bazarr, Seerr and Jellyfin databases and configuration plus qBittorrent's settings and torrent list, copied with SQLite's online backup API so nothing stops. Logs, caches and re-downloadable artwork are left out (about 20 MB instead of 1.8 GB). Same pre-flight checks, retention, history and alerts as the photo backup, and a **Back up now** button on the backup card.
- Photo backup health (Control Hub Phase 2A). The backup script runs pre-flight checks before anything else and stops with a clear reason if the remote does not answer, a backup folder on it went missing, the photo folder is empty (an unmounted disk), or there is not enough space. It records transfer totals, retention and the last 30 runs in `status.json`, and never runs twice at once.
- Retention for database dumps: 3 on the server, and on the remote the newest 14 plus the first of each of the last 12 months (profile keys `photo_backup_keep_local`, `photo_backup_keep_remote`, `photo_backup_keep_monthly`). Only files the nightly script names are deleted.
- The backup card shows the last good run and its age, the next run, the last 7 runs, the failed pre-flight checks and what retention will delete next. It turns red when the last run failed or was interrupted, or the last good run is older than 26 hours, and the log refreshes live during a run.
- Install profile keys `photo_external_mount_path` and `photo_external_mount_mode` set where and how the photo server mounts the external library. Defaults stay `/mnt/media` and read-only. A library moved from another install keeps the paths its database recorded.
- Alerts (Control Hub Phase 2B): ntfy, Telegram, Discord or email when the photo backup fails, is interrupted or is older than 26 hours, the backup remote stops answering, a disk passes 85% or 95%, an app is stopped or unhealthy for 5 minutes, the CPU stays above 80 °C, a TV app update fails, or dashboard sign-ins are locked out. Each alert is sent once, repeated daily while open and followed by "Resolved"; quiet hours hold non-critical alerts until morning. Set up under Alerts in the dashboard, with a test button per channel.
- TVs in the Control Hub can be given a nickname. Without one, a TV is shown by the model it reports itself (for example "Xiaomi MIBOX4"). Hovering over the name shows a summary; clicking it shows manufacturer, codename, Android version, the TV's own name, address and last seen, and lets you rename it.

### Changed
- The installer checks the photo backup remote with `rclone lsd` and refuses the module with rclone's error if it does not answer, instead of installing a job that fails every night. A missing `rclone` is now an error, not a warning.
- The Control Hub works on phones and with a keyboard or screen reader: one responsive layout with three breakpoints and no `!important` rules, a compact header with a menu, bottom tabs on phones, collapsible cards, 44 px tap targets, 12 px minimum text, accessible dialogs (focus trap, Esc, focus return), landmarks, a skip link, a visible focus ring, a live region for toasts and reduced motion. "Hover Only" refresh is gone: visible cards refresh on a timer and hidden tabs pause.
- CI runs the Control Hub in a browser at 360, 820 and 1366 px and fails on sideways scrolling, clipped controls, small tap targets or serious axe-core findings, and a test fails if any endpoint returns one of the old invented figures.
- The Control Hub asks for a password instead of the access token. By default it is the master password from setup (profile key `control_hub_password` sets another), each browser signs in once with a long-lived HttpOnly cookie, and it can be changed under Account in the dashboard or with `sudo ./setup.sh password`. Changing it signs other devices out. The API token still works for scripts and CI, and is accepted at the sign-in prompt.
- Pinned images now match what the existing server already runs, so moving that server to v2 does not downgrade any app: Radarr 7.0.3, Prowlarr 3.0.2, Seerr 3.5.2 and Noodle Gallery 5.11.1. These apps migrate their databases forward and cannot open them after a downgrade.
- The optional Byparr proxy is pinned to 3.1.1. The old 1.0.7 pin had no amd64 image, so the profile could not start on a PC.
- The gallery machine-learning service sets `MACHINE_LEARNING_MODEL_REVISION: v2`, as the upstream v5 compose file does.

### Fixed
- After switching to another backup remote, the first backup would have stopped with "folder missing although earlier runs wrote to it". Both backups now remember which remote their last good run used.
- The TV card showed a model taken from the first entry of the profile's model list ("SHIELD" for a Mi Box) and showed offline TVs as up to date. It now shows the model the TV reports (or none until it has been online), and an offline TV's versions say "when last seen". The model is read after `adb connect`, so it is also found for a TV the server has not talked to since a restart.
- A backup started with "Run backup now" ran inside the Control Hub's service, so restarting the Control Hub killed it and the hub's 100 MB memory cap applied to the database dump and rclone. The script now moves itself into its own transient systemd unit (`photo-backup-<time>`).
- The Control Hub no longer shows invented numbers. Backup, Google Drive, photo library, speed test, storage split, service ping and TV figures come from real data, or say "Unknown" with the reason. Backup status starts as unknown and turns green only from a real result: the photo backup script now writes `status.json` (0644, atomic) next to its log, and the dashboard reads it without `sudo rclone`.
- The Control Hub reads the photo backup from `/var/lib/homelab/photo-backups` by default, matches the v2 log line `Starting Immich Backup:`, and gets `GDRIVE_REMOTE`, `HDD_MEMORIES` and `TZ` from the installer. Times use the host time zone instead of a fixed IST.
- Media and photo folder sizes are measured with `du` at low priority in the background, cached to disk and refreshed hourly, instead of a fixed 75/20/5 split.
- The Service Matrix, its filter counts and the footer list only the containers that exist on the host. Restarting a container no longer calls `sudo docker`, which the sudoers file does not allow.
- The service user `homelab` gets a home directory (`/var/lib/homelab/home`) so its ADB key survives a reboot, and the Control Hub unit and TV cron job set `HOME` to it. The installer creates the directory itself rather than copying `/etc/skel`.
- "Run backup now" in the Control Hub used the default `gdrive:` remote and failed, because sudo clears the settings cron passes in. The backup script now reads any unset setting from `/etc/cron.d/immich-backup`.
- The TV auto-updater no longer writes each log line twice under cron, and names the configured TVs instead of three fixed models. It logs through its own logger, so the Control Hub (which imports it for TV status) no longer writes its HTTP access log into `tv-autoupdater.log`.
- qBittorrent 5.3 logins (HTTP 204) and the v2 Samba shares are recognised by the live telemetry; the static IP dialog says 120 s, matching the revert timer.
- The installer crashed on Python 3.14 (Ubuntu 26.04): `setup/token.py` shadowed the standard `token` module once argparse started importing it. The file is now `setup/token_cli.py`, a test refuses files named after standard modules, and CI also runs on Python 3.14.
- The Control Hub could not be installed on Ubuntu 26.04, whose sudo-rs rejects the wildcard in `--on-calendar=*`. Tonight's sleep override now runs through `/usr/local/sbin/server-suspend-override.sh`, which validates the time, and a test checks the sudoers template against sudo-rs rules.
- The optional Byparr container never turned healthy during install: its image checks every 15 minutes. The compose file now checks every 30 seconds.
- `docs/INSTALL_ON_EXISTING_SERVER.md` explains how to keep an existing photo database whose password was a default.

## [2.1.1] - 2026-11-21

### Fixed
- The Control Hub, Setup Wizard, installer and API spec reported version 2.0.0 in v2.1.0.

### Added
- A test that fails when the reported version strings and the newest changelog release disagree.

## [2.1.0] - 2026-11-21

### Added
- Four modules are published as their own read-only repositories on every release: [control-hub](https://github.com/RAM-MAHESHWARI24/control-hub), [homelab-mediaserver](https://github.com/RAM-MAHESHWARI24/homelab-mediaserver), [noodle-gallery-tools](https://github.com/RAM-MAHESHWARI24/noodle-gallery-tools) and [tv-autoupdater](https://github.com/RAM-MAHESHWARI24/tv-autoupdater). See [docs/RELEASING.md](docs/RELEASING.md).
- Each published module has its own `install.sh` for use without the blueprint, a `ci.sh` and a `module.json`.
- A module contract test and a CI job that runs each module's checks in an isolated copy.

### Changed
- `apps/tv-updater` is now `apps/tv-autoupdater`.
- Host scripts and cron templates moved from `system/` into the module they belong to. Installed paths on the server are unchanged.
- The Control Hub's TV card is hidden unless the TV auto-updater is installed.

### Fixed
- The Control Hub's backup card read the old `/opt/immich/backups` path instead of the folder the photo backup writes to.
- The Control Hub container could not reach qBittorrent on the host.
- The media stack and photo tools no longer ship a regional time zone or a server-specific backup path as defaults.

## [2.0.0] - 2026-11-15

A rewrite of the installer around a single goal: a fresh Ubuntu server installed from the browser comes up fully wired.

### Added
- Bearer-token authentication for the Setup Wizard (one-time token in the printed link) and the Control Hub (`sudo ./setup.sh token [--rotate]`).
- Automatic wiring of the media stack by `wire_arr.py`: qBittorrent password seeding, download clients, root folders, Prowlarr app sync, Jellyfin startup and libraries, Seerr setup.
- Indexer picker in the Control Hub over Prowlarr's own definition list, with nothing pre-selected.
- Static-IP changes guarded by a systemd revert timer and confirmed from the new address.
- Install manifest at `/var/lib/homelab/installed.json`; `teardown.sh` removes exactly what was installed.
- Opt-in modules: photo ML schedule, photo backup, Samba shares, Tailscale forwarding, Byparr, TMDB bypass, container DNS override.
- Post-wake hooks in `/etc/server-suspend.d/`, with an Arr recovery hook from the media module.
- TV auto-updater verifies each APK's signing certificate against pinned fingerprints.
- Optional image pins for an existing photo library (`photos_server_image`, `photos_ml_image`).
- Pinned container images, healthchecks, Dependabot, and a CI job that performs a real install, checks the wiring and tears it down again.
- A Playwright test that installs on a fresh VM through the browser, including a static-IP change. See the [v2.0.0 Test Report](docs/V2_TEST_REPORT.md).

### Changed
- Configuration moved to `/etc/homelab/`, container data to `/srv/homelab/appdata/`, state to `/var/lib/homelab/`.
- The Control Hub runs as the unprivileged `homelab` user with an exact-argument sudoers file.
- Defaults are neutral: timezone and network interface are detected, regional workarounds are opt-in.
- `bootstrap.sh` installs the latest release tag by default.

### Fixed
- Static IP changes from the wizard or Control Hub now take effect on hosts where cloud-init configures the interface, use the interface's real prefix instead of assuming /24, and no longer cut off the browser's request before the confirm step.
- The install no longer fails on slow hardware when an app's first start takes several minutes.
- The static-IP confirm button in the install dialog is reachable on any screen size.

### Removed
- Watchtower; images are updated through Dependabot pull requests.
- Shipped default passwords.
- HD Streamz from the TV updater; only official GitHub release sources remain.
- The `RootFS` Samba share.

## [1.1.0]

Earlier releases predate this changelog.
