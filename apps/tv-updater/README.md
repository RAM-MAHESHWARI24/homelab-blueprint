# CleanYourTV - Automated Background App Updater for Android TVs 📺

> Zero-overhead, server-orchestrated background sideload updater for Android TVs over network ADB.  
> Keeps SmartTube, CloudStream, and custom APKs updated silently without consuming TV memory or interrupting playback.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![ADB Network](https://img.shields.io/badge/ADB-Port%205555-orange.svg)](#architecture)

---

## 🏗️ 2-Tier Architecture

Running updaters (Obtainium, Shizuku, auto-update daemons) directly on low-spec Android TV dongles (1GB–2GB RAM) consumes background resources, causing video stutters and sluggish menus. 

**CleanYourTV** moves all downloading, version diffing, and scheduling to the server:

```
┌──────────────────────────────────────────────────────────────────┐
│  Tier 1: Daily Upstream Sync (Once every 24h, or on --sync)      │
│  • Checks GitHub APIs (SmartTube, CloudStream) & HD Streamz      │
│  • Caches new genuine APKs in cache/                             │
│  • Updates target versionCodes in state.json                     │
└─────────────────────────────────┬────────────────────────────────┘
                                  │
                                  ▼
┌──────────────────────────────────────────────────────────────────┐
│  Tier 2: Opportunistic Local Deployment (15-min cron)            │
│                                                                  │
│  Are ANY TVs missing apps, outdated, or incoming_apks/ dropped?  │
│       │                                                          │
│       ├── NO  ──> STOP POLLING & EXIT IMMEDIATELY (<5ms, 0 net)  │
│       │                                                          │
│       └── YES ──> Probe ONLY the pending TV(s)                   │
│                   • Fresh Install if app is not yet installed    │
│                   • Update if installed vCode < target vCode     │
│                   • Foreground Guard: skip only if in target app │
│                   • Mark TV as UP_TO_DATE in state.json          │
│                   • When all TVs updated -> HALT POLLING         │
└──────────────────────────────────────────────────────────────────┘
```

---

## 📦 Supported Apps & Drops

1. **SmartTube Stable** (`org.smarttube.stable`): Automated tracking of `yuliskov/SmartTube` GitHub releases (ARMv7a).
2. **CloudStream Beta** (`com.lagradost.cloudstream3.prerelease`): Automated tracking of `recloudstream/cloudstream` GitHub pre-releases with server-side versionCode diffing.
3. **HD Streamz** (`topic.election.sector`): Automated fetching with developer keystore verification (`5E:AA:CA:0A:...`) to prevent signature mismatch errors.
4. **Manual Sideload Drops**: Any APK dropped into `incoming_apks/` is silently pushed across all TVs and archived to `installed_apks/`.

---

## 🛡️ Non-Disruptive Silent Installation

* **Zero Dialogs:** ADB package installations (`adb install -r`) execute at the OS daemon level.
* **Playback Safe:** Video playback on Netflix, YouTube, or Jellyfin continues uninterrupted during background installs.
* **Foreground Guard:** If the user is actively using the *target app* being updated, installation is safely postponed until they exit.

---

## 🚀 Quickstart & Setup

### 1. Requirements
* Linux or macOS server with Python 3.10+
* Android Debug Bridge (`adb`) installed on the host (`sudo apt install adb`)
* Android TVs connected to the same local network

### 2. Prepare Android TV
1. On your Android TV, navigate to: **Settings -> Device Preferences -> About**.
2. Click **Build** 7 times to enable Developer Options.
3. In **Developer Options**, turn ON **USB Debugging** and **Network ADB Debugging** (port 5555).
4. Connect from your server once:
   ```bash
   adb connect 192.168.1.150:5555
   ```
5. Check "Always allow from this computer" on the TV screen.

### 3. Configuration
Copy `config.example.json` to `config.json` and specify your TV device profiles:
```bash
cp config.example.json config.json
nano config.json
```

```json
{
  "subnet_prefix": "192.168.1",
  "dhcp_scan_range": [32, 100],
  "target_profiles": [
    {
      "id": "living_room_tv",
      "name": "Living Room TV",
      "match_models": ["mibox4", "oneday"],
      "default_ip": "192.168.1.150",
      "port": 5555
    },
    {
      "id": "bedroom_tv",
      "name": "Bedroom TV",
      "match_models": ["mitv-axfr0", "rango", "mitv"],
      "default_ip": "192.168.1.151",
      "port": 5555
    }
  ]
}
```

### 4. Running
* **Check Cluster Status:**
  ```bash
  python3 tv_updater.py --status
  ```
* **Sync Upstream Releases:**
  ```bash
  python3 tv_updater.py --sync
  ```
* **Trigger Deployment:**
  ```bash
  python3 tv_updater.py --deploy
  ```
* **Install Background Cron (every 15 min):**
  ```bash
  bash setup_cron.sh
  ```

---

## 🖥️ Live Monitoring on Control Hub
Android TV fleet status is integrated directly into [Control Hub](../control-hub/):
* **Living Room & Bedroom TV Card:** Visual status indicators (`UP TO DATE`, `PENDING`, `OFFLINE`).
* **Active Version Tracking:** Displays target vs installed versionCodes for SmartTube, CloudStream, and custom sideloads.
* **1-Click Sync:** Trigger updates or inspect ADB logs directly from the browser without opening SSH.

---

## 📄 License
MIT License. Part of the [Homelab Blueprint](../../README.md) monorepo.
