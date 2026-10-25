# Homelab Setup Wizard ⚡🧙

> Zero-dependency, browser-based onboarding and provisioning wizard for Ubuntu Homelab Servers.  
> Runs entirely on the Python 3 standard library with zero `pip install` requirements.

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Zero-Dependency](https://img.shields.io/badge/Dependencies-Standard%20Library%20Only-success.svg)](#architecture)
[![Port: 8000](https://img.shields.io/badge/Port-8000-orange.svg)](#quickstart)

---

## 🌟 Why a Zero-Dependency Setup Wizard?

When setting up a fresh Ubuntu Server or mini-PC, installing Node.js, npm packages, or heavy Python web frameworks before the server is even configured creates a chicken-and-egg problem. 

The **Homelab Setup Wizard** is designed with strict engineering constraints:
* **Zero External Dependencies:** Built solely on Python's built-in `http.server`, `socket`, `subprocess`, `urllib`, and `json` modules.
* **Runs on Clean Installs:** Executes immediately on a barebones Ubuntu Server with default Python 3.
* **Non-Destructive Dry-Run Support:** Supports a full simulation mode (`dry_run: true`) that writes preview configs to `setup/dry_run_preview/` without touching production filesystems or network interfaces.
* **Zero-Downtime Safe Netplan:** Validates static IP configurations using `netplan generate` and `netplan try --timeout 45` to prevent locking the administrator out of SSH.
* **Atomic Hardlink Inode Tester:** Performs real-time `os.link` file system probes to guarantee 0-I/O hardlinks before any media containers are spun up.

---

## 🚀 Quickstart

### Launching the Wizard

From the homelab repository root:
```bash
# Standard launch
python3 setup/server.py

# Or via the automated setup script
sudo ./setup.sh
```

Terminal output:
```
============================================================
  HOMELAB BLUEPRINT - ONBOARDING WIZARD
============================================================
  Web UI: http://192.168.1.31:8000
  Local:  http://127.0.0.1:8000
============================================================
```

Open `http://<your-server-ip>:8000` from any browser on your local network (laptop, tablet, or phone).

---

## 🧭 The Three Onboarding Modes

### 1. ⚡ Express Mode ("Least Setup")
Designed for 60-second onboarding. Asks only for the essentials:
* **Single Mount Media/Data Path** (e.g. `/mnt/hdd/data` with 1-click auto-detected drive chips).
* **Family Photos Path** (e.g. `/mnt/hdd/Memories`).
* **Master Password** (with 1-click high-entropy CSPRNG generator).
* **Safe Netplan Static IP Toggle** (auto-detects current LAN IP and gateway).

![Express Mode Initial View](../docs/assets/setup-wizard/express_mode_stage1_initial.png)
![Express Mode Verified](../docs/assets/setup-wizard/express_mode_stage2_verified.png)

### 2. 🛠️ Power User Mode
Full granular control across all 5 monorepo subsystems:
* **Network & Host Architecture:** Static IP, Subnet mask, Gateway, DNS, Timezone, Active NIC.
* **Storage & Paths:** SSD config paths, HDD root mount, download categories (`torrents/movies`, `torrents/tv`).
* **Modular Stack Toggles:** Individual checkboxes for Media Stack, Noodle Photo Cloud, CleanYourTV, and Sleep Guard.
* **Smart Defaults:** Every optional field displays a default badge and a 1-click **"Keep Default"** reset action.
* **Security & Secrets:** 1-Click **"⚡ Auto-Generate All"** for database credentials and *arr API keys.

![Power User Mode](../docs/assets/setup-wizard/power_user_stage1_network_storage.png)
![Power User Verified](../docs/assets/setup-wizard/power_user_stage2_hardlink_verified.png)

### 3. 🤖 AI Copilot Mode
For users working with AI coding assistants (ChatGPT, Claude, Cursor, Antigravity):
* Gathers live hardware diagnostics (CPU architecture, core count, RAM, detected disks, and `/dev/dri` GPU render nodes).
* Generates a token-optimized prompt (~300 tokens) ready to copy/paste into an LLM for personalized architecture advice.
* Recommends optimal hardware-specific flags (e.g. Haswell Direct Play, VAAPI driver selection).

![AI Copilot Mode](../docs/assets/setup-wizard/ai_copilot_mode.png)

---

## 🔌 REST API Endpoints

The wizard server exposes lightweight JSON endpoints on port `8000`:

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/health` | Healthcheck and server state |
| `GET` | `/api/probe` | Live hardware auto-detection (CPU, RAM, NICs, IP, Disks) |
| `GET` | `/api/ai/context` | Generates token-optimized AI copilot diagnostic prompt |
| `POST` | `/api/verify/hardlink` | Runs live `os.link` probe to test atomic hardlink support |
| `POST` | `/api/secrets/generate` | Generates cryptographically secure passwords and API keys |
| `POST` | `/api/netplan/preview` | Returns generated Netplan YAML configuration |
| `POST` | `/api/deploy` | Executes configuration deployment pipeline (supports `dry_run: true`) |

---

## 🧪 Automated Verification Suite

Run the built-in automated test suite to verify all endpoints, HTML assets, and deployment logic:
```bash
python3 setup/test_setup.py
```

Expected output:
```
Testing GET /api/health... -> {'status': 'healthy'}
Testing GET /api/probe... -> Detected hardware & NICs
Testing GET /api/ai/context... -> Prompt generated
Testing POST /api/verify/hardlink... -> Hardlink verified
Testing POST /api/secrets/generate... -> Secrets generated
Testing GET static HTML, CSS, JS... -> Assets OK
Testing POST /api/deploy (dry_run=True)... -> Deployed cleanly
ALL TESTS PASSED WITH 100% SUCCESS!
```

---

## 🔗 Seamless Handoff to Control Hub

Upon successful deployment, the setup wizard automatically hands off orchestration to the **Control Hub** command center:
* Displays clickable direct launch links for each deployed service.
* Runs an 8-second visual auto-redirect countdown to `http://<server-ip>:7575`.
* Shuts down port `8000` or keeps it standby for fast reconfiguration.

![Success Screen](../docs/assets/setup-wizard/express_mode_stage4_success.png)
