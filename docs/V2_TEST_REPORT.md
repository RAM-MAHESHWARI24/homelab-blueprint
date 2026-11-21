# v2 Test Report

This report records how v2.0.0 and v2.1.0 were tested, what passed, and which bugs the tests found. Evidence from the passing runs is stored in this repository so it stays with the code it describes.

**Status on 2026-11-21:** every automated check passes on both test paths below. v2.1.0 also passed the module checks in [section 6](#6-v210-module-repositories).

## 1. What was tested, and how

Two independent end-to-end tests install the blueprint for real, with no mocks. They cover different things.

| Test | Where it runs | What it drives | What it proves |
| :--- | :--- | :--- | :--- |
| CI `real-install` | GitHub Actions, fresh Ubuntu 24.04 runner, on every push | Headless install from a JSON profile | Installer, permissions, app wiring, Control Hub, and a teardown that leaves nothing behind |
| GUI end-to-end | Fresh Multipass VM on a developer machine, started by hand | The Setup Wizard and Control Hub in a real Chromium browser | The few-clicks path a person takes, including a static-IP change confirmed from the new address |

Both tests also check, inside the installed host, that the apps are wired together and not just running. That check lives in [`testing/vm/check_wiring.sh`](../testing/vm/check_wiring.sh):

- Radarr and Sonarr have qBittorrent as download client and their root folders.
- Prowlarr has Radarr and Sonarr as applications.
- Jellyfin finished its startup wizard; Seerr is initialised.
- qBittorrent accepts the generated password and refuses anonymous calls.
- The Control Hub accepts its token, refuses calls without it, and can read the Prowlarr key.
- The photo server answers, and its database lives under appdata, not in the checkout.

## 2. GUI end-to-end test

**Script:** [`testing/vm/test_wizard_gui.py`](../testing/vm/test_wizard_gui.py), using Playwright and Multipass.

It follows the README quickstart exactly:

1. Launch a clean Ubuntu 24.04 VM (4 CPU, 6 GB RAM, 40 GB disk).
2. Run `bootstrap.sh --branch refactor/v2`, which clones from GitHub and prints the wizard link.
3. Open the link in Chromium. Check the host probe, the pre-filled IP, the empty password field and that static IP is off by default.
4. In express mode, switch off dry run, tick "lock static IP" and enter a different free address. Click install.
5. Check the result page: credentials shown once, pointer to the indexer picker, static-IP confirm box.
6. Wait until the old page sees the server on the new address, continue there and confirm.
7. Land on the Control Hub at the new address. Open the indexer picker, check Prowlarr's list is shown with nothing ticked, then skip.
8. Wait past the 120-second revert window. Check the new address still answers, the old one does not, and the revert timer is gone.
9. Run `check_wiring.sh` inside the VM.

### Result of the passing run

Run on 2026-11-15 against `refactor/v2` at commit `d5a0907`, installed through `bootstrap.sh` from GitHub. The VM changed address from 172.20.87.176 to 172.20.87.76. All 23 checks passed in 13.5 minutes, of which the install took about 8.

| Step | Result | Detail |
| :--- | :--- | :--- |
| VM launched | Pass | 172.20.87.176 |
| Wizard printed its token URL | Pass | http://172.20.87.176:8000/?token=<redacted> |
| Wizard loads and probes the host | Pass | 172.20.87.176 (eth0) |
| Express mode pre-fills the server's current IP | Pass | field=172.20.87.176 vm=172.20.87.176 |
| Express master password is empty (no shipped default) | Pass |  |
| Static IP is off by default | Pass |  |
| Deploy result reached the browser | Pass | 472s |
| Credentials are shown once (Control Hub token present) | Pass |  |
| Wizard points at the indexer picker | Pass |  |
| Static-IP confirm box is shown | Pass |  |
| Old page detects the server on the new address | Pass | Server reachable on 172.20.87.76. Continue there to keep this IP. |
| Static IP confirmed from the new address | Pass | Static IP confirmed. Opening the dashboard... |
| Browser handed over to the Control Hub | Pass | http://172.20.87.76:7575/ |
| Dashboard shows the one-time indexer banner | Pass |  |
| Picker lists Prowlarr's definitions | Pass | 400 shown |
| Nothing is pre-selected | Pass | 0 ticked |
| Add button disabled until something is picked | Pass |  |
| Indexer step can be skipped | Pass |  |
| Control Hub still answers on the new address after the revert window | Pass |  |
| Old address no longer answers | Pass |  |
| VM interface carries the new address | Pass | eth0 172.20.87.76/20 |
| Revert timer is gone | Pass |  |
| Apps wired inside the VM (check_wiring.sh) | Pass |  |

### Recorded run

A second full run on 2026-11-15 recorded a video of the browser session, at commit `6d29087`, after the fixes for the last two bugs in section 4. All 23 checks passed again in 10.1 minutes; the VM changed address from 172.20.86.120 to 172.20.86.220.

- Video: [`session.webm`](assets/test-runs/2026-11-15-gui-e2e-video/session.webm). The one-time credentials are blurred on screen during recording.
- Screenshots and logs: [`docs/assets/test-runs/2026-11-15-gui-e2e-video/`](assets/test-runs/2026-11-15-gui-e2e-video/).

Evidence for the first run: [`docs/assets/test-runs/2026-11-15-gui-e2e/`](assets/test-runs/2026-11-15-gui-e2e/) holds the screenshots, `summary.json`, the step log, the wizard log, the browser's deploy log and the wiring-check output. Secrets are redacted and the credentials box is masked in screenshots.

## 3. CI `real-install`

**Workflow:** [`.github/workflows/ci.yml`](../.github/workflows/ci.yml), job "Real Headless Install, Health Probes & Teardown".

First fully green run: `43679665458` at commit `c67f6f1`. Every later push has run it again. It confirmed the wiring end to end, 661 Prowlarr indexer definitions served to the Control Hub, the Prowlarr key file at `0640 root:homelab`, and a teardown that removes every file, unit and user it created.

## 4. Bugs the tests found

Each of these was found by one of the two tests, fixed, and confirmed fixed by a later run. Runs that failed while finding them are not stored; their findings are listed here.

| Found by | Problem | Fix |
| :--- | :--- | :--- |
| CI | Seerr ignores PUID/PGID and could not write its config folder | Run it with `user: PUID:PGID` |
| CI | The Control Hub service could not enter a checkout under a home folder | Preflight check; CI installs from `/opt/homelab-blueprint` |
| CI | A stack whose health wait failed was not recorded, so teardown left it running | Record it right after `up -d` |
| CI | `wire_arr.py` shadowed Python's `http` module | Import `CookieJar` by name |
| CI | `teardown.sh` and three scripts were committed without the executable bit | Mode fixed in git |
| CI | qBittorrent 5.3 answers a good login with HTTP 204, not 200 "Ok." | Login confirmed with an authenticated call; `LocalHostAuth` stays on |
| CI | The Prowlarr key file was `root:root` because the service user was created too late | Create the service user before any module |
| CI | Registry rate limits (HTTP 429) failed image pulls | Pulls retry with backoff |
| GUI | The static IP never applied on hosts where cloud-init names the interface `default` | Write the static config under the netplan ID that owns the interface |
| GUI | The static IP always used a /24 prefix, which breaks the default route on larger networks | Use the interface's current prefix |
| GUI | The address changed during the install request, so the browser lost the result, never saw the confirm step, and the change reverted | Apply the new address 5 seconds after the reply (Control Hub: 3 seconds) |
| GUI | On a heavily loaded VM, Radarr's first start outlasted its healthcheck grace period and Compose aborted the media stack | Healthchecks allow 5 minutes to start and check every 5 seconds meanwhile; the installer retries `up` once |
| GUI | The install dialog did not scroll, so the static-IP "Continue" button sat below the screen edge and the change reverted | The dialog scrolls; the confirm box sits under the credentials and is scrolled into view |

## 5. What these tests do not cover

- **Real hardware and a home router.** The VM sits behind Hyper-V's NAT switch. A bridged VM or a real machine on a LAN is the next step.
- **Power-mode options.** Samba, Tailscale, Sleep Guard, photo backup, the TV auto-updater and the regional workarounds are installed by unit-level tests and the deployer's dry run, not by these two end-to-end tests.
- **Suspend and wake.** Sleep Guard's suspend cycle needs real hardware.
- **Upgrading an existing server.** That path is a manual runbook: [Installing v2 on an Existing Server](INSTALL_ON_EXISTING_SERVER.md).
- **Look and feel.** The GUI test checks that things work. A person still needs to read the screens once. Reading this run's screenshots found two problems, fixed after the run: the credentials box appeared below the static-IP box that says "save the credentials above", and the page subtitle still promised "under 60 seconds".

## 6. v2.1.0: module repositories

v2.1.0 is the first release that publishes four module folders as their own repositories (see [RELEASING.md](RELEASING.md)). Four checks covered that path:

| Check | Result |
| :--- | :--- |
| Module contract on every pull request ([`test_module_contract.py`](../testing/test_module_contract.py)) | Pass: required files present, no code or README link leaves its module |
| Split simulation in CI: each module copied out alone, running its own `ci.sh` with ShellCheck and Docker | Pass for all four |
| Split workflow dry run on `main` (run `44858521723`) | Pass: each module's history built, 13 to 82 files, nothing pushed |
| Release `v2.1.0` (split run `44858733310`) | Pass: all four repositories received `main` and the tag; each repository's own CI then passed |

**Clean-machine install.** On a fresh Ubuntu 24.04 VM, two published repositories were cloned from GitHub at `v2.1.0` and installed exactly as their READMEs say. 16 of 16 checks passed:

- **homelab-mediaserver:** `install.sh` exited 0 with 26 wiring steps succeeding and none failing. All 7 containers became healthy. Radarr had qBittorrent as its download client, Prowlarr had Radarr and Sonarr, and Jellyfin had finished its setup. `.env` held generated passwords at mode 600, the credentials were printed at the end, and a second run was safe.
- **control-hub:** `install.sh` generated a 48-character token in a mode-600 `.env`. `run.sh` started the dashboard, which accepted the token, refused an anonymous request with 401, and reported the TV card as not installed.

`noodle-gallery-tools` and `tv-autoupdater` passed their own CI but were not installed on the VM: they need a running Immich library and real Android TVs.

**Found on the way to v2.1.0:**

| Problem | Fix |
| :--- | :--- |
| The Control Hub's backup card read the old `/opt/immich/backups` path, so v2 installs never showed backups | The installer points it at `/var/lib/homelab/photo-backups` |
| The Control Hub container could not reach qBittorrent on the host | Compose uses `host.docker.internal` |
| The Control Hub's TV card reached into a neighbouring module's folder | The card appears only when the TV module is installed |
| The media stack and photo tools shipped a regional time zone and a server-specific backup path as defaults | Neutral defaults |
| The code still reported version 2.0.0 after v2.1.0 was released | Fixed after the release; the next release reports its own version |

## 7. How to run the tests

CI runs on every push. To run the GUI test on Windows, macOS or Linux:

```bash
pip install playwright && python -m playwright install chromium
python testing/vm/test_wizard_gui.py                  # pushed branch, via bootstrap.sh
python testing/vm/test_wizard_gui.py --source local   # local HEAD, unpushed commits
python testing/vm/test_wizard_gui.py --headed --keep-vm --video
```

A run takes 15 to 25 minutes, mostly image downloads. Reports go to `testing/vm/reports/gui/<timestamp>/`, which git ignores. Copy a run you want to keep into `docs/assets/test-runs/`.

On Windows, the script works around three Multipass quirks: `multipass exec` stalls after 4 KB of output, `multipass transfer` reads `C:` as an instance name, and Multipass loses a VM whose address changed. See the comments in the script.
