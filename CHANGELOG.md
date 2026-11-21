# Changelog

All notable changes to this project are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed
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

### Added
- Install profile keys `photo_external_mount_path` and `photo_external_mount_mode` set where and how the photo server mounts the external library. Defaults stay `/mnt/media` and read-only. A library moved from another install keeps the paths its database recorded.

### Changed
- The Control Hub works on phones and with a keyboard or screen reader: one responsive layout with three breakpoints and no `!important` rules, a compact header with a menu, bottom tabs on phones, collapsible cards, 44 px tap targets, 12 px minimum text, accessible dialogs (focus trap, Esc, focus return), landmarks, a skip link, a visible focus ring, a live region for toasts and reduced motion. "Hover Only" refresh is gone: visible cards refresh on a timer and hidden tabs pause.
- CI runs the Control Hub in a browser at 360, 820 and 1366 px and fails on sideways scrolling, clipped controls, small tap targets or serious axe-core findings, and a test fails if any endpoint returns one of the old invented figures.
- The Control Hub asks for a password instead of the access token. By default it is the master password from setup (profile key `control_hub_password` sets another), each browser signs in once with a long-lived HttpOnly cookie, and it can be changed under Account in the dashboard or with `sudo ./setup.sh password`. Changing it signs other devices out. The API token still works for scripts and CI, and is accepted at the sign-in prompt.
- Pinned images now match what the existing server already runs, so moving that server to v2 does not downgrade any app: Radarr 7.0.3, Prowlarr 3.0.2, Seerr 3.5.2 and Noodle Gallery 5.11.1. These apps migrate their databases forward and cannot open them after a downgrade.
- The optional Byparr proxy is pinned to 3.1.1. The old 1.0.7 pin had no amd64 image, so the profile could not start on a PC.
- The gallery machine-learning service sets `MACHINE_LEARNING_MODEL_REVISION: v2`, as the upstream v5 compose file does.

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
