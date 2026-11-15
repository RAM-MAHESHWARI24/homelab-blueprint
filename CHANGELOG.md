# Changelog

All notable changes to this project are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [2.0.0]

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
