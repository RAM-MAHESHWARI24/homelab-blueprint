# Changelog

All notable changes to this project are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed
- The installer crashed on Python 3.14 (Ubuntu 26.04): `setup/token.py` shadowed the standard `token` module once argparse started importing it. The file is now `setup/token_cli.py`, a test refuses files named after standard modules, and CI also runs on Python 3.14.

### Added
- Install profile keys `photo_external_mount_path` and `photo_external_mount_mode` set where and how the photo server mounts the external library. Defaults stay `/mnt/media` and read-only. A library moved from another install keeps the paths its database recorded.

### Changed
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
