# Homelab Blueprint

A browser-driven installer for an Ubuntu home server. It sets up a media stack, a photo library and a dashboard, and connects the apps to each other so they work together without manual configuration.

[![CI](https://github.com/RAM-MAHESHWARI24/homelab-blueprint/actions/workflows/ci.yml/badge.svg)](https://github.com/RAM-MAHESHWARI24/homelab-blueprint/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## What it does

- **Installs and wires the media chain.** qBittorrent, Prowlarr, Radarr, Sonarr, Bazarr, Jellyfin and Seerr come up with download clients, root folders, Prowlarr app sync, Jellyfin libraries and Seerr already configured.
- **Adds a photo library** (Open-Noodle Gallery, an Immich fork) with optional scheduled ML, a face-tag XMP exporter and nightly backup.
- **Runs a dashboard**, the Control Hub, for health, downloads, cron jobs, sleep scheduling and static-IP changes.
- **Changes the server's IP safely.** A new static address is reverted automatically unless you confirm it from the new address.
- **Offers opt-ins** for Sleep Guard (scheduled suspend and wake), Samba shares, Tailscale subnet routing, an Android TV app updater, and regional workarounds (Byparr, TMDB bypass, container DNS override).

## What it does not do

- It does not choose indexers for you. After install, the Control Hub lists Prowlarr's own indexer definitions with nothing selected. No tracker list ships in this repository.
- It does not expose anything to the internet. There is no reverse proxy, TLS or domain setup. Keep it on your LAN or behind Tailscale.
- It does not update container images on its own. Every image is pinned, and Dependabot proposes updates as pull requests.

## Requirements

- Ubuntu Server 24.04 (22.04 also works) on x86-64 or arm64.
- One data disk or directory for media, mounted before install. Downloads and the library share one mount so hardlinks work.
- About 15 GB free for images. The photo ML image alone is several GB.

Docker and the other packages the installer needs are installed by the setup script.

## Quickstart

On the server:

```bash
curl -sSL https://raw.githubusercontent.com/RAM-MAHESHWARI24/homelab-blueprint/main/bootstrap.sh | sudo bash
```

This clones the latest release to `/opt/homelab-blueprint` and starts the Setup Wizard. It prints a link like `http://<server-ip>:8000/?token=...`. Open it from any device on your LAN, then:

1. Pick the data folder and set one password, or leave it blank to have one generated.
2. Tick the modules you want.
3. Click install. A first install takes around 10 minutes, mostly image downloads.
4. Save the credentials the wizard shows once. It then hands over to the Control Hub at `http://<server-ip>:7575`.
5. In the Control Hub, pick indexers from Prowlarr's list, or skip.

To install from a clone instead:

```bash
sudo git clone https://github.com/RAM-MAHESHWARI24/homelab-blueprint.git /opt/homelab-blueprint
cd /opt/homelab-blueprint
./setup.sh --doctor        # optional pre-flight check
sudo ./setup.sh
```

Unattended installs take a JSON profile, for example [`testing/fixtures/ci_minimal.json`](testing/fixtures/ci_minimal.json):

```bash
sudo ./setup.sh --headless --config my-profile.json
```

## Modules

| Module | Folder | What you get | On its own |
| :--- | :--- | :--- | :--- |
| Media stack | [`apps/mediaserver/`](apps/mediaserver/) | Arr apps, qBittorrent, Jellyfin, Seerr, all wired by `wire_arr.py` | [homelab-mediaserver](https://github.com/RAM-MAHESHWARI24/homelab-mediaserver) |
| Photo library | [`apps/noodle-gallery/`](apps/noodle-gallery/) | Open-Noodle Gallery with Postgres and Valkey | Blueprint only |
| Photo tools | [`apps/immich-face-xmp-exporter/`](apps/immich-face-xmp-exporter/) | Face-tag XMP export, ML on/off schedule, nightly backup | [noodle-gallery-tools](https://github.com/RAM-MAHESHWARI24/noodle-gallery-tools) |
| Control Hub | [`apps/control-hub/`](apps/control-hub/) | Dashboard, indexer picker, Sleep Guard, static-IP changes | [control-hub](https://github.com/RAM-MAHESHWARI24/control-hub) |
| TV auto-updater | [`apps/tv-autoupdater/`](apps/tv-autoupdater/) | Keeps SmartTube and CloudStream current on Android TVs over ADB, with pinned signing keys | [tv-autoupdater](https://github.com/RAM-MAHESHWARI24/tv-autoupdater) |
| Host extras | [`system/`](system/) | Samba shares, Tailscale forwarding | Blueprint only |

Already running your own homelab? Each module marked with a repository installs on its own with its `install.sh`. Those repositories are read-only mirrors published from this one on every release; see [Releasing](docs/RELEASING.md).

## Where things live

| Path | Contents |
| :--- | :--- |
| `/opt/homelab-blueprint` | The checkout. Replaceable. |
| `/etc/homelab/` | Wizard output, one env file per module (mode 0600), Control Hub token |
| `/srv/homelab/appdata/` | Container configs and databases |
| `/var/lib/homelab/installed.json` | Every file, unit and cron job the installer created |
| Your data folder | Media, default `/mnt/hdd/data` |

## Security

- **Token-protected.** The Setup Wizard prints a one-time token. The Control Hub requires a bearer token, shown by `sudo ./setup.sh token`. Only health endpoints are open.
- **No default passwords.** Blank fields mean a generated secret, shown once after install.
- **The Control Hub is root-equivalent.** It runs as the `homelab` user, which is in the `docker` group. Anyone with the token controls the host. Treat the token like a root password.
- **LAN only.** Do not port-forward 7575, 8000 or the app ports. Use Tailscale for remote access.

See [SECURITY.md](SECURITY.md) to report a problem.

## Indexers and your responsibility

You choose which indexers to add, and you are responsible for that choice and for following the law where you live. This project ships no indexer or tracker list.

## Uninstall

```bash
sudo ./teardown.sh             # interactive; keeps media, photos and app databases
sudo ./teardown.sh --dry-run   # show what would be removed
sudo ./teardown.sh --purge-data
```

Teardown reads the install manifest and removes only what the installer created. `--purge-data` also deletes container configs and databases.

## Documentation

- [Documentation hub](docs/README.md)
- [Installing on a server that already runs these apps](docs/INSTALL_ON_EXISTING_SERVER.md)
- [Static IP changes and rollback](docs/NETPLAN_STATIC_IP_QUIRKS.md)
- [Storage and hardlinks](docs/STORAGE_AND_HARDLINKS.md)
- [Releasing and the module repositories](docs/RELEASING.md)
- [Test report](docs/V2_TEST_REPORT.md)
- [Changelog](CHANGELOG.md)

## License

MIT. See [LICENSE](LICENSE).
