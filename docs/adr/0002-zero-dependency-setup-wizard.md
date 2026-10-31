# ADR-0002: Zero-Dependency Standard-Library-Only Setup Wizard

## Status
**Accepted**

## Context
When bootstrapping a bare-metal server, mini-PC, or fresh Ubuntu minimal installation, third-party software packages and package managers are not guaranteed:
1. `pip` or Python virtual environment tools (`python3-venv`, `pip3`) are often not installed on fresh server installations.
2. Network connectivity during initial setup may be firewalled, slow, or restricted by captive portals.
3. Third-party Python dependencies (Flask, FastAPI, Requests, PyYAML) introduce package version conflicts and build tool requirements (`gcc`, `python3-dev`).
4. If the setup tool requires a 200 MB dependency chain just to configure the network or static IP, failure rates on edge devices skyrocket.

## Decision
The **Phase 1 Setup Wizard (`setup/`)** and core configuration libraries must be strictly **zero-dependency**:
1. Powered exclusively by Python 3 standard library modules:
   * `http.server` & `socketserver` for the multi-threaded HTTP web server and REST API.
   * `urllib.parse` & `json` for request/response serialization.
   * `socket` for raw port probing and network interface discovery.
   * `secrets` for cryptographically secure token and password generation.
   * `ctypes` & `subprocess` for cross-platform hardware discovery (Linux, Windows, macOS).
   * `pathlib` & `os` for filesystem manipulation and `os.link` hardlink validation.
2. Zero external Python packages (`pip install`) are permitted inside the `setup/` directory.
3. The wizard runs directly upon executing `./setup.sh` or `python setup/setup_server.py`.

## Alternatives Considered
* **FastAPI + Uvicorn:**
  * *Rejected:* Requires compilation of C extensions (`pydantic-core`, `uvloop`), pip installation, and high memory overhead for a one-time bootstrap wizard.
* **Flask + Gunicorn:**
  * *Rejected:* Adds external wheel requirements before the system is even configured with internet or apt repositories.
* **Pure Bash / Whiptail (CLI-only):**
  * *Rejected:* Extremely difficult to provide real-time hardware graphing, copy-to-clipboard buttons, live port checking, and remote browser access from a tablet/phone on the LAN.

## Consequences
### Positive
* **100% Bootstrap Reliability:** Starts instantly on any pristine Linux machine with Python 3.8+ installed.
* **Zero Network Dependency:** Operates fully air-gapped without needing PyPI access.
* **Extreme Memory Efficiency:** The entire setup server consumes < 15 MB RAM.
* **Universal Remote Management:** Operators can open `http://<ip>:8000` from their mobile phone, tablet, or workstation to complete server onboarding.

### Negative / Trade-offs
* Low-level HTTP routing and JSON parsing must be handled manually via `BaseHTTPRequestHandler` (implemented cleanly in `setup/setup_server.py`).
* Web UI assets (HTML/CSS/JS) must be bundled locally without external CDN dependencies.

## References
* [Setup Wizard Implementation](../../setup/setup_server.py)
* [Setup Architecture Guide](../../setup/README.md)
* [Lifecycle Test TC-FLOW-01](../../testing/test_lifecycle_handoff.py)

